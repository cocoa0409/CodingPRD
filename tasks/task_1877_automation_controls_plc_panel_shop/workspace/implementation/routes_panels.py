"""Routes: panels (lifecycle) and panel BOM lines."""

from flask import Blueprint, request

from calc import line_extended_cost, recompute_sccr, reevaluate_job_posture
from core import (
    bump,
    envelope_object,
    err_duplicate,
    err_inactive,
    err_invalid_request,
    err_invalid_state,
    err_job_gate,
    err_not_found,
    err_panel_not_ready,
    err_ref_not_found,
    err_sccr,
    err_sod,
    get_body,
    now_dt,
    now_iso,
    opt_int,
    paginate,
    req_enum,
    req_int,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import (
    asbuilt_of_panel,
    get_component,
    get_job,
    get_line,
    get_panel,
    job_of_panel,
)
from serializers import ser_panel, ser_panel_component
from store import db

bp = Blueprint("panels", __name__)

ENCLOSURE_RATINGS = ("NEMA_1", "NEMA_12", "NEMA_4", "NEMA_4X")


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


@bp.route("/panel-shop/jobs/<job_id>/panels", methods=["POST"])
def create_panel(job_id):
    require_roles("DesignEngineer")
    j = get_job(job_id)
    body = get_body()
    panel_tag = req_str(body, "panel_tag")
    enclosure = req_enum(body, "enclosure_rating", ENCLOSURE_RATINGS)
    design_engineer_id = req_str(body, "design_engineer_id")
    # panel_tag unique within the job
    if any(
        p["job_id"] == job_id and p["panel_tag"] == panel_tag for p in db.panels.values()
    ):
        raise err_duplicate("panel_tag already exists within this job.")
    p = stamp_new(
        {
            "job_id": job_id,
            "panel_tag": panel_tag,
            "status": "DESIGN",
            "enclosure_rating": enclosure,
            "design_engineer_id": design_engineer_id,
            "sccr_rating_ka": 0,
            "label_serial": None,
            "shipped_at": None,
            "commissioned_at": None,
            "_shipped_dt": None,
            "_commissioned_dt": None,
        }
    )
    db.panels[p["id"]] = p
    # AsBuiltPackage auto-created with all flags false
    pkg = stamp_new(
        {
            "panel_id": p["id"],
            "status": "INCOMPLETE",
            "has_wiring_diagram": False,
            "has_program_archive": False,
            "has_test_report": False,
            "has_ul_label_photo": False,
            "completeness_pct": 0,
        }
    )
    db.as_built_packages[pkg["id"]] = pkg
    # first panel also advances Job OPEN -> DESIGN
    if j["status"] == "OPEN":
        j["status"] = "DESIGN"
        bump(j)
    else:
        reevaluate_job_posture(j)
    return envelope_object(ser_panel(p), 201)


@bp.route("/panel-shop/panels/<panel_id>", methods=["GET"])
def fetch_panel(panel_id):
    require_roles(
        "ProjectManager",
        "QAManager",
        "DesignEngineer",
        "ShopLead",
        "TestTechnician",
        "ControlsEngineer",
        "FieldEngineer",
        "Customer",
        "ShippingClerk",
    )
    return envelope_object(ser_panel(get_panel(panel_id)))


@bp.route("/panel-shop/panels", methods=["GET"])
def list_panels():
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    panels = list(db.panels.values())
    if "job_id" in request.args:
        panels = [p for p in panels if p["job_id"] == request.args.get("job_id")]
    if "status" in request.args:
        panels = [p for p in panels if p["status"] == request.args.get("status")]
    return paginate(sorted_by_created(panels), ser_panel)


@bp.route("/panel-shop/panels/<panel_id>/submit-review", methods=["POST"])
def submit_review(panel_id):
    require_roles("DesignEngineer")
    p = get_panel(panel_id)
    if p["status"] != "DESIGN":
        raise err_invalid_state("Panel is not in DESIGN.")
    recompute_sccr(p)
    # priority 9 (SCCR floor) surfaces before the unnumbered panel-not-ready gate
    if p["sccr_rating_ka"] < 5:
        raise err_sccr("Panel SCCR below the 5 kA minimum.")
    if not any(l["panel_id"] == panel_id for l in db.panel_components.values()):
        raise err_panel_not_ready("Panel has no BOM lines.")
    p["status"] = "DESIGN_REVIEW"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/approve-design", methods=["POST"])
def approve_design(panel_id):
    user_id, _ = require_roles("QAManager")
    p = get_panel(panel_id)
    if p["status"] != "DESIGN_REVIEW":
        raise err_invalid_state("Panel is not in DESIGN_REVIEW.")
    if user_id == p["design_engineer_id"]:
        raise err_sod("QAManager may not approve their own design.")
    p["status"] = "DESIGN_APPROVED"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/reject-design", methods=["POST"])
def reject_design(panel_id):
    require_roles("QAManager")
    p = get_panel(panel_id)
    if p["status"] != "DESIGN_REVIEW":
        raise err_invalid_state("Panel is not in DESIGN_REVIEW.")
    p["status"] = "DESIGN"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/release-procurement", methods=["POST"])
def release_procurement(panel_id):
    require_roles("ProjectManager")
    p = get_panel(panel_id)
    if p["status"] != "DESIGN_APPROVED":
        raise err_invalid_state("Panel is not DESIGN_APPROVED.")
    j = job_of_panel(p)
    if j["status"] not in ("DESIGN", "PROCUREMENT"):
        raise err_job_gate("Parent job has progressed beyond the procurement gate.")
    for l in [l for l in db.panel_components.values() if l["panel_id"] == panel_id]:
        if l["line_status"] == "PENDING":
            l["line_status"] = "ORDERED"
            bump(l)
    p["status"] = "PROCUREMENT"
    bump(p)
    reevaluate_job_posture(j)
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/start-wiring", methods=["POST"])
def start_wiring(panel_id):
    require_roles("ShopLead")
    p = get_panel(panel_id)
    if p["status"] != "PROCUREMENT":
        raise err_invalid_state("Panel is not in PROCUREMENT.")
    lines = [l for l in db.panel_components.values() if l["panel_id"] == panel_id]
    if any(l["line_status"] not in ("RECEIVED", "SUBSTITUTED") for l in lines):
        raise err_panel_not_ready("Not all BOM lines are RECEIVED or SUBSTITUTED.")
    p["status"] = "WIRING"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/begin-test", methods=["POST"])
def begin_test(panel_id):
    require_roles("ShopLead")
    p = get_panel(panel_id)
    if p["status"] != "WIRING":
        raise err_invalid_state("Panel is not in WIRING.")
    if not any(t["panel_id"] == panel_id for t in db.test_points.values()):
        raise err_panel_not_ready("Panel has no test points.")
    p["status"] = "POINT_TO_POINT"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/rework", methods=["POST"])
def rework(panel_id):
    require_roles("ShopLead")
    p = get_panel(panel_id)
    if p["status"] != "TEST_FAILED":
        raise err_invalid_state("Panel is not TEST_FAILED.")
    for t in [t for t in db.test_points.values() if t["panel_id"] == panel_id]:
        if t["result"] in ("PASS", "FAIL", "SKIPPED"):
            t["result"] = "UNTESTED"
    p["status"] = "WIRING"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/request-label", methods=["POST"])
def request_label(panel_id):
    require_roles("QAManager")
    p = get_panel(panel_id)
    if p["status"] != "TEST_PASSED":
        raise err_invalid_state("Panel is not TEST_PASSED.")
    if not any(
        v["panel_id"] == panel_id and v["status"] == "RELEASED"
        for v in db.program_versions.values()
    ):
        raise err_panel_not_ready("No RELEASED ProgramVersion for this panel.")
    if any(
        s["panel_id"] == panel_id and s["status"] in ("REQUESTED", "COUNTERED")
        for s in db.substitution_requests.values()
    ):
        raise err_panel_not_ready("Panel has open substitution requests.")
    p["status"] = "READY_FOR_LABEL"
    bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel(p))


@bp.route("/panel-shop/panels/<panel_id>/affix-label", methods=["POST"])
def affix_label(panel_id):
    user_id, _ = require_roles("QAManager")
    p = get_panel(panel_id)
    if p["status"] != "READY_FOR_LABEL":
        raise err_invalid_state("Panel is not READY_FOR_LABEL.")
    if user_id == p["design_engineer_id"]:
        raise err_sod("QAManager may not affix the label on their own design.")
    j = job_of_panel(p)
    p["label_serial"] = "UL-%s-%s-1" % (j["job_number"], p["panel_tag"])
    p["status"] = "LABELED"
    bump(p)
    pkg = asbuilt_of_panel(panel_id)
    if pkg is not None and not pkg["has_ul_label_photo"]:
        pkg["has_ul_label_photo"] = True
        from calc import recompute_asbuilt

        recompute_asbuilt(pkg)
    reevaluate_job_posture(j)
    return envelope_object(ser_panel(p))


# ---------------------------------------------------------------------------
# Panel BOM lines (PanelComponent)
# ---------------------------------------------------------------------------


@bp.route("/panel-shop/panels/<panel_id>/components", methods=["POST"])
def add_bom_line(panel_id):
    require_roles("DesignEngineer")
    p = get_panel(panel_id)
    body = get_body()
    component_id = body.get("component_id")
    quantity = body.get("quantity")
    # priority 5: body FK
    if isinstance(component_id, str) and component_id:
        component = db.components.get(component_id)
        if component is None:
            raise err_ref_not_found("component_id does not reference an existing Component.")
    else:
        raise err_invalid_request("Missing or invalid required field: component_id")
    # priority 15: inactive component
    if not component["active"]:
        raise err_inactive("Component is inactive.")
    # priority 16: duplicate component on a panel
    if any(
        l["panel_id"] == panel_id and l["component_id"] == component_id
        for l in db.panel_components.values()
    ):
        raise err_duplicate("Component already present on this panel.")
    # priority 22: shape
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise err_invalid_request("quantity must be an integer >= 1.")
    line = stamp_new(
        {
            "panel_id": panel_id,
            "component_id": component_id,
            "quantity": quantity,
            "line_status": "PENDING",
            "substituted_for_id": None,
            "unit_cost_snapshot_cents": component["unit_cost_cents"],
            "extended_cost_cents": 0,
        }
    )
    line["extended_cost_cents"] = line_extended_cost(line)
    db.panel_components[line["id"]] = line
    recompute_sccr(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel_component(line), 201)


@bp.route("/panel-shop/panels/<panel_id>/components", methods=["GET"])
def list_panel_components(panel_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    get_panel(panel_id)
    lines = [l for l in db.panel_components.values() if l["panel_id"] == panel_id]
    if "line_status" in request.args:
        lines = [l for l in lines if l["line_status"] == request.args.get("line_status")]
    return paginate(sorted_by_created(lines), ser_panel_component)


@bp.route("/panel-shop/panel-components/<line_id>", methods=["GET"])
def fetch_bom_line(line_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    return envelope_object(ser_panel_component(get_line(line_id)))


@bp.route("/panel-shop/panel-components", methods=["GET"])
def list_bom_lines():
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    lines = list(db.panel_components.values())
    args = request.args
    if "panel_id" in args:
        lines = [l for l in lines if l["panel_id"] == args.get("panel_id")]
    if "component_id" in args:
        lines = [l for l in lines if l["component_id"] == args.get("component_id")]
    if "substituted_for_id" in args:
        lines = [l for l in lines if l.get("substituted_for_id") == args.get("substituted_for_id")]
    if "line_status" in args:
        lines = [l for l in lines if l["line_status"] == args.get("line_status")]
    return paginate(sorted_by_created(lines), ser_panel_component)


@bp.route("/panel-shop/components/<component_id>/panel-components", methods=["GET"])
def list_component_usage(component_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    get_component(component_id)
    lines = [l for l in db.panel_components.values() if l["component_id"] == component_id]
    return paginate(sorted_by_created(lines), ser_panel_component)


@bp.route("/panel-shop/panel-components/<line_id>", methods=["PATCH"])
def update_bom_line(line_id):
    require_roles("DesignEngineer")
    line = get_line(line_id)
    body = get_body()
    if line["line_status"] != "PENDING":
        raise err_invalid_state("Only a PENDING line may change quantity.")
    quantity = req_int(body, "quantity")
    if quantity < 1:
        raise err_invalid_request("quantity must be >= 1.")
    line["quantity"] = quantity
    line["extended_cost_cents"] = line_extended_cost(line)
    bump(line)
    p = db.panels[line["panel_id"]]
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel_component(line))


@bp.route("/panel-shop/panel-components/<line_id>/receive", methods=["POST"])
def receive_bom_line(line_id):
    require_roles("ShopLead")
    line = get_line(line_id)
    if line["line_status"] != "ORDERED":
        raise err_invalid_state("Only an ORDERED line may be received.")
    line["line_status"] = "RECEIVED"
    bump(line)
    p = db.panels[line["panel_id"]]
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_panel_component(line))
