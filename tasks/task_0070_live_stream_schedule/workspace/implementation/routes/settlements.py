"""Commission-settlement payout endpoint."""

from flask import Blueprint

import db
from errors import ERR_INVALID_STATE, ERR_NOT_FOUND, raise_err
from middleware import require_auth, require_role
from response import success
from services import audit
from services.streamer_service import apply_cascade


bp = Blueprint("settlements", __name__, url_prefix="/live-schedule/settlements")


@bp.post("/<sid>/payout")
def payout(sid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    settlement = db.raw_get("settlements", sid)
    if settlement is None:
        raise_err(ERR_NOT_FOUND, "Settlement not found")

    if settlement.get("status") != "READY_FOR_PAYOUT":
        raise_err(ERR_INVALID_STATE, "Settlement is not READY_FOR_PAYOUT")

    effective_sales = (int(settlement.get("gross_sales_cents", 0))
                       - int(settlement.get("returned_sales_cents", 0)))

    def m_settle(s):
        s["status"] = "PAID"
    updated = db.update_entity("settlements", sid, m_settle)

    # Bump streamer's lifetime_gmv_cents and cascade tier/suspension.
    app = db.raw_get("applications", settlement["application_id"])
    if app is not None:
        streamer_id = app["streamer_id"]
        # Also bring the net_payout_cents onto the application
        def m_app(a, np=int(settlement.get("final_payout_cents", 0))):
            a["net_payout_cents"] = np
        db.update_entity("applications", app["id"], m_app)

        def m_streamer(s, delta=effective_sales):
            s["lifetime_gmv_cents"] = s.get("lifetime_gmv_cents", 0) + delta
        db.update_entity("streamers", streamer_id, m_streamer)
        apply_cascade(streamer_id)

    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=settlement.get("application_id"),
        action="PAID",
        actor_role=role,
        actor_id=user_id,
        from_state="READY_FOR_PAYOUT",
        to_state="PAID",
        payload_snapshot={"settlement_id": sid,
                          "final_payout_cents": settlement.get("final_payout_cents", 0)},
    )
    return success(updated)
