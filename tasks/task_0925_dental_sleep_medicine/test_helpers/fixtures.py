"""Composite setup helpers.

Every precondition these helpers build is constructed through PRD-declared
endpoints only — there is no implementation-side seeding.  The harness restarts
the server before each test, so each helper starts from an empty database.

The clinical timeline they walk is the one the whole suite shares:

    2026-05-01  cast registered, HSAT recorded on 2026-04-10 and resulted,
                referral raised and accepted, lab case opened, submitted,
                shipped 2026-05-15, accepted, device fabricated,
                standard written order written 2026-05-10 against a
                2026-04-20 encounter and signed 2026-05-11
    2026-06-01  device delivered, proof of delivery captured, visit 1 applied
    2026-06-15  visit 2 applied
    2026-06-29  visit 3 applied, plateau declared
    2026-07-06  efficacy study (performed 2026-07-05) reported, report drafted
                and submitted
    2026-07-07  physician response
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import assert_same_instant
from .constants import TIMELINE
from .factories import (
    create_adherence_download_payload,
    create_appliance_lot_payload,
    create_appliance_payload,
    create_claim_payload,
    create_efficacy_report_payload,
    create_lab_order_payload,
    create_patient_payload,
    create_payer_payload,
    create_prior_auth_payload,
    create_provider_payload,
    create_referral_payload,
    create_repair_order_payload,
    create_sleep_study_payload,
    create_titration_visit_payload,
    create_written_order_payload,
    sleep_study_results_payload,
)
from .test_users import (
    TEST_USERS,
    make_dentist_headers,
    make_lab_technician_headers,
    make_patient_headers,
    make_sleep_physician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["clinic_coordinator_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]

_STAGES = [
    "cast",
    "diagnosed",
    "referral_issued",
    "referral_accepted",
    "lab_shipped",
    "lab_accepted",
    "fabricated",
    "written_order",
    "written_order_signed",
    "delivered",
    "titrated",
    "plateau",
    "efficacy_drafted",
    "efficacy_submitted",
    "active_therapy",
]


def _rank(stage: str) -> int:
    assert stage in _STAGES, f"unknown stage {stage!r}"
    return _STAGES.index(stage)


# ---------------------------------------------------------------------------
# Thin single-call helpers
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock; returns the {current_utc} object.

    The echoed setting is compared as an instant, never as a raw string: the
    response re-renders the caller's value canonically, so a textual comparison
    would fail on a correct implementation.
    """
    data = get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))
    assert_same_instant(data["current_utc"], to_iso8601, "clock current_utc")
    return data


def register_payer(**overrides) -> dict:
    return get_success_data(
        api_client.create_payer(create_payer_payload(**overrides), ADMIN)
    )


def register_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides), ADMIN)
    )


def register_patient(medical_payer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(medical_payer_id, **overrides), COORD
        )
    )


def read_patient_version(patient_id: str) -> int:
    return get_success_data(api_client.get_patient(patient_id, COORD))["version"]


def read_appliance_version(appliance_id: str, dentist_headers: dict) -> int:
    return get_success_data(
        api_client.get_appliance(appliance_id, dentist_headers)
    )["version"]


def read_referral_version(referral_id: str, headers: dict) -> int:
    return get_success_data(api_client.get_referral(referral_id, headers))["version"]


def order_and_result_study(
    scenario: dict, results=None, study_overrides=None
) -> dict:
    """Order a study and post its recording.  Returns the resulted study row."""
    study_overrides = dict(study_overrides or {})
    study = get_success_data(
        api_client.create_sleep_study(
            create_sleep_study_payload(
                scenario["pat_id"], scenario["phys_id"], **study_overrides
            ),
            scenario["phys_headers"],
        )
    )
    if results is None:
        return study
    return get_success_data(
        api_client.post_sleep_study_results(
            study["id"], sleep_study_results_payload(**results), scenario["phys_headers"]
        )
    )


def issue_and_sign_written_order(
    scenario: dict, sign: bool = True, signed_on: str = None, **overrides
) -> dict:
    """Issue a standard written order, re-reading the patient version first."""
    version = read_patient_version(scenario["pat_id"])
    order = get_success_data(
        api_client.create_written_order(
            create_written_order_payload(
                scenario["pat_id"], scenario["phys_id"], version, **overrides
            ),
            scenario["phys_headers"],
        )
    )
    if sign:
        order = get_success_data(
            api_client.sign_written_order(
                order["id"],
                {"signed_on": signed_on or TIMELINE["signed_on"]},
                scenario["phys_headers"],
            )
        )
    return order


def open_and_accept_lab_case(
    scenario: dict, shipped_on: str = None, accept: bool = True, **overrides
) -> dict:
    """Records to accepted fit in one hop; returns the lab order row."""
    lab_order = get_success_data(
        api_client.create_lab_order(
            create_lab_order_payload(
                scenario["ref_id"], scenario["lab_id"], **overrides
            ),
            scenario["dent_headers"],
        )
    )
    get_success_data(
        api_client.submit_lab_order(lab_order["id"], {}, scenario["dent_headers"])
    )
    lab_order = get_success_data(
        api_client.ship_lab_order(
            lab_order["id"],
            {"shipped_on": shipped_on or TIMELINE["shipped_on"]},
            scenario["lab_headers"],
        )
    )
    if accept:
        lab_order = get_success_data(
            api_client.receive_lab_order(
                lab_order["id"], {"fit_outcome": "ACCEPTED"}, scenario["dent_headers"]
            )
        )
    return lab_order


def fabricate_appliance(scenario: dict, lab_order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_appliance(
            create_appliance_payload(lab_order_id, scenario["lot_id"], **overrides),
            scenario["dent_headers"],
        )
    )


def schedule_and_apply_visit(
    scenario: dict,
    appliance_id: str = None,
    severity: str = "NONE",
    scheduled_for: str = None,
    requested_increment_mm: float = 1.00,
) -> tuple:
    """Create a visit against a freshly read appliance version, then apply it."""
    appliance_id = appliance_id or scenario["app_id"]
    version = read_appliance_version(appliance_id, scenario["dent_headers"])
    visit = get_success_data(
        api_client.create_titration_visit(
            create_titration_visit_payload(
                appliance_id,
                scenario["dent_id"],
                version,
                scheduled_for=scheduled_for or TIMELINE["visit_1"],
                requested_increment_mm=requested_increment_mm,
            ),
            scenario["dent_headers"],
        )
    )
    applied = get_success_data(
        api_client.apply_titration_visit(
            visit["id"], {"side_effect_severity": severity}, scenario["dent_headers"]
        )
    )
    return visit, applied


def schedule_visit(
    scenario: dict,
    appliance_id: str = None,
    scheduled_for: str = None,
    requested_increment_mm: float = 1.00,
) -> dict:
    """Create a visit only — leaves it SCHEDULED."""
    appliance_id = appliance_id or scenario["app_id"]
    version = read_appliance_version(appliance_id, scenario["dent_headers"])
    return get_success_data(
        api_client.create_titration_visit(
            create_titration_visit_payload(
                appliance_id,
                scenario["dent_id"],
                version,
                scheduled_for=scheduled_for or TIMELINE["visit_1"],
                requested_increment_mm=requested_increment_mm,
            ),
            scenario["dent_headers"],
        )
    )


def record_adherence(scenario: dict, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_adherence_download(
            create_adherence_download_payload(scenario["app_id"], **overrides),
            headers or scenario["dent_headers"],
        )
    )


def draft_claim(scenario: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(
                scenario["pat_id"], scenario["payer_med_id"], scenario["app_id"],
                **overrides,
            ),
            BILLING,
        )
    )


def open_repair(scenario: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_repair_order(
            create_repair_order_payload(scenario["app_id"], **overrides),
            scenario["dent_headers"],
        )
    )


def file_prior_auth(scenario: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_prior_auth(
            create_prior_auth_payload(
                scenario["pat_id"], scenario["payer_med_id"], scenario["ref_id"],
                **overrides,
            ),
            BILLING,
        )
    )


def open_audit_hold(scenario: dict, **overrides) -> dict:
    payload = {
        "patient_id": scenario["pat_id"],
        "payer_id": scenario["payer_med_id"],
        "scope_note": "Records audit",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_audit_hold(payload, ADMIN))


# ---------------------------------------------------------------------------
# The staged scenario builder
# ---------------------------------------------------------------------------


def build_scenario(stage: str = "cast", **opts) -> dict:
    """Walk the shared clinical timeline up to `stage` and return the context.

    Recognised options:
      payer_overrides, with_dental_payer, patient_overrides, second_patient,
      extra_dentist, suspended_dentist, touch_clock,
      study_overrides, study_results,
      referral_overrides,
      lab_order_overrides, spare_appliance, appliance_overrides,
      written_order_overrides, sign_written_order, signed_on,
      delivery_clock, delivered_on, with_pod, pod_method, pod_signed_on,
      visit_count, visit_dates, visit_increment,
      efficacy_events, efficacy_performed_on, efficacy_clock, response_clock
    """
    want = _rank(stage)
    s: dict = {}

    # ---------------------------------------------------------------- cast
    s["payer"] = register_payer(
        **{"prior_auth_required": False, **opts.get("payer_overrides", {})}
    )
    s["payer_med_id"] = s["payer"]["id"]
    if opts.get("with_dental_payer"):
        s["dental_payer"] = register_payer(name="DentaCare", payer_kind="DENTAL")
        s["payer_dent_id"] = s["dental_payer"]["id"]

    s["phys"] = register_provider(
        npi="1000000001", full_name="Dr Sleep", provider_type="SLEEP_PHYSICIAN"
    )
    s["phys_id"] = s["phys"]["id"]
    s["phys_headers"] = make_sleep_physician_headers(s["phys_id"])

    s["dent"] = register_provider(
        npi="1000000002", full_name="Dr Dent", provider_type="DENTIST",
        dme_supplier_number="DME-001",
    )
    s["dent_id"] = s["dent"]["id"]
    s["dent_headers"] = make_dentist_headers(s["dent_id"])

    s["lab"] = register_provider(
        npi="1000000003", full_name="ACME Lab", provider_type="DENTAL_LAB"
    )
    s["lab_id"] = s["lab"]["id"]
    s["lab_headers"] = make_lab_technician_headers(s["lab_id"])

    if opts.get("extra_dentist"):
        s["dent2"] = register_provider(
            npi="1000000006", full_name="Dr Stranger", provider_type="DENTIST"
        )
        s["dent2_id"] = s["dent2"]["id"]
        s["dent2_headers"] = make_dentist_headers(s["dent2_id"])

    if opts.get("suspended_dentist"):
        s["dent_susp"] = register_provider(
            npi="1000000007", full_name="Dr Paused", provider_type="DENTIST",
            status="SUSPENDED",
        )
        s["dent_susp_id"] = s["dent_susp"]["id"]

    patient_overrides = dict(opts.get("patient_overrides", {}))
    if opts.get("with_dental_payer"):
        patient_overrides.setdefault("dental_payer_id", s["payer_dent_id"])
    s["patient"] = register_patient(s["payer_med_id"], **patient_overrides)
    s["pat_id"] = s["patient"]["id"]
    s["patient_headers"] = make_patient_headers(s["pat_id"])

    if opts.get("second_patient"):
        s["patient2"] = register_patient(
            s["payer_med_id"], mrn="MRN-002", full_name="Pat Two",
            date_of_birth="1970-02-02",
        )
        s["pat2_id"] = s["patient2"]["id"]
        s["patient2_headers"] = make_patient_headers(s["pat2_id"])

    if opts.get("touch_clock", True):
        set_clock(TIMELINE["intake"])

    s["admin_headers"] = ADMIN
    s["coord_headers"] = COORD
    s["billing_headers"] = BILLING
    if want == _rank("cast"):
        return s

    # ----------------------------------------------------------- diagnosed
    s["study"] = order_and_result_study(
        s,
        results=dict(opts.get("study_results", {})),
        study_overrides=opts.get("study_overrides"),
    )
    s["study_id"] = s["study"]["id"]
    if want == _rank("diagnosed"):
        return s

    # ------------------------------------------------------ referral issued
    s["referral"] = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                s["pat_id"], s["phys_id"], s["dent_id"], s["study_id"],
                **opts.get("referral_overrides", {}),
            ),
            s["phys_headers"],
        )
    )
    s["ref_id"] = s["referral"]["id"]
    if want == _rank("referral_issued"):
        return s

    # ---------------------------------------------------- referral accepted
    s["referral"] = get_success_data(
        api_client.respond_to_referral(
            s["ref_id"], {"decision": "ACCEPTED"}, s["dent_headers"]
        )
    )
    if want == _rank("referral_accepted"):
        return s

    # ---------------------------------------------------------- lab shipped
    lab_overrides = dict(opts.get("lab_order_overrides", {}))
    s["lab_order"] = open_and_accept_lab_case(
        s, accept=(want >= _rank("lab_accepted")), **lab_overrides
    )
    s["lo_id"] = s["lab_order"]["id"]
    if want <= _rank("lab_accepted"):
        return s

    # ---------------------------------------------------------- fabricated
    s["lot"] = get_success_data(
        api_client.create_appliance_lot(create_appliance_lot_payload(), ADMIN)
    )
    s["lot_id"] = s["lot"]["id"]
    s["appliance"] = fabricate_appliance(
        s, s["lo_id"], **opts.get("appliance_overrides", {})
    )
    s["app_id"] = s["appliance"]["id"]

    if opts.get("spare_appliance"):
        s["lab_order2"] = open_and_accept_lab_case(
            s, shipped_on="2026-05-16", **lab_overrides
        )
        s["lo2_id"] = s["lab_order2"]["id"]
        s["spare"] = fabricate_appliance(s, s["lo2_id"], serial_number="SN-0002")
        s["spare_id"] = s["spare"]["id"]
    if want == _rank("fabricated"):
        return s

    # -------------------------------------------------------- written order
    s["written_order"] = issue_and_sign_written_order(
        s,
        sign=(want >= _rank("written_order_signed")),
        signed_on=opts.get("signed_on"),
        **opts.get("written_order_overrides", {}),
    )
    s["wo_id"] = s["written_order"]["id"]
    if want <= _rank("written_order_signed"):
        return s

    # ------------------------------------------------------------ delivered
    set_clock(opts.get("delivery_clock", TIMELINE["delivery"]))
    s["appliance"] = get_success_data(
        api_client.deliver_appliance(
            s["app_id"],
            {
                "delivered_on": opts.get("delivered_on", TIMELINE["delivered_on"]),
                "written_order_id": s["wo_id"],
            },
            s["dent_headers"],
        )
    )
    if opts.get("with_pod", True):
        s["appliance"] = get_success_data(
            api_client.capture_proof_of_delivery(
                s["app_id"],
                {
                    "pod_signed_on": opts.get(
                        "pod_signed_on", opts.get("delivered_on", TIMELINE["delivered_on"])
                    ),
                    "pod_method": opts.get("pod_method", "IN_PERSON"),
                },
                s["dent_headers"],
            )
        )
    if want == _rank("delivered"):
        return s

    # ------------------------------------------------------------- titrated
    visit_dates = opts.get(
        "visit_dates", [TIMELINE["visit_1"], TIMELINE["visit_2"], TIMELINE["visit_3"]]
    )
    count = opts.get("visit_count", 3)
    s["visits"] = []
    for index in range(count):
        day = visit_dates[index]
        set_clock(f"{day}T00:00:00Z")
        _created, applied = schedule_and_apply_visit(
            s,
            scheduled_for=day,
            requested_increment_mm=opts.get("visit_increment", 1.00),
        )
        s["visits"].append(applied)
    s["visit_ids"] = [v["id"] for v in s["visits"]]
    if want == _rank("titrated"):
        return s

    # -------------------------------------------------------------- plateau
    s["appliance"] = get_success_data(
        api_client.declare_plateau(s["app_id"], {}, s["dent_headers"])
    )
    if want == _rank("plateau"):
        return s

    # ------------------------------------------------------ efficacy drafted
    s["eff_study"] = order_and_result_study(
        s,
        results={
            "performed_on": opts.get(
                "efficacy_performed_on", TIMELINE["efficacy_performed_on"]
            ),
            "respiratory_events": opts.get("efficacy_events", 32),
            "recording_minutes": 480,
            "artifact_pct": 0,
        },
        study_overrides={
            "modality": "HSAT",
            "study_purpose": "EFFICACY",
            "appliance_id": s["app_id"],
        },
    )
    s["eff_study_id"] = s["eff_study"]["id"]
    set_clock(opts.get("efficacy_clock", TIMELINE["efficacy_draft"]))
    s["ref_version_before_report"] = read_referral_version(s["ref_id"], s["dent_headers"])
    s["report"] = get_success_data(
        api_client.create_efficacy_report(
            create_efficacy_report_payload(
                s["ref_id"], s["app_id"], s["eff_study_id"],
                s["ref_version_before_report"],
            ),
            s["dent_headers"],
        )
    )
    s["rep_id"] = s["report"]["id"]
    if want == _rank("efficacy_drafted"):
        return s

    # ---------------------------------------------------- efficacy submitted
    s["report"] = get_success_data(
        api_client.submit_efficacy_report(s["rep_id"], {}, s["dent_headers"])
    )
    if want == _rank("efficacy_submitted"):
        return s

    # ------------------------------------------------------- active therapy
    set_clock(opts.get("response_clock", TIMELINE["physician_response"]))
    s["report"] = get_success_data(
        api_client.physician_respond_to_efficacy_report(
            s["rep_id"], {"decision": "SIGNED"}, s["phys_headers"]
        )
    )
    return s
