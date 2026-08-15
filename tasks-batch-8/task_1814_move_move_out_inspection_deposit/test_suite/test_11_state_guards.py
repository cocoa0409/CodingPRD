"""State-machine guards: give_notice before OCCUPIED, re-completing an
inspection, and key returns frozen at VACATED."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_inspection,
    create_jurisdiction,
    create_property,
    create_tenancy,
    create_unit,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    schedule_inspection,
    setup_occupied_tenancy,
    setup_vacated_tenancy,
    validate_error,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestGiveNoticeGuard:
    def test_give_notice_before_occupied_rejected(self):
        """PRD §3.3: "When the tenant gives notice, a `PropertyManager`
        records it against an `OCCUPIED` tenancy: the tenancy moves from
        `OCCUPIED` to `NOTICE_GIVEN`". PRD §2.9: "fifth, state preconditions
        on the target resources (the state-guard errors such as
        `ERR_INVALID_STATE_TRANSITION` and `ERR_TENANCY_NOT_VACATED`)".

        give_notice from PENDING_MOVE_IN has no transition; the tenancy state
        is unchanged.

        Design: Corner/state_machines/give_notice_before_occupied_rejected
        """
        _jur, _prop, units = th.setup_portfolio()
        ten = create_tenancy(units[0]["id"], lease_start_on="2026-09-01",
                             lease_end_on="2027-09-01")
        assert ten["status"] == "PENDING_MOVE_IN"
        resp = api_client.give_notice(ten["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_tenancy(ten["id"])["status"] == "PENDING_MOVE_IN"


class TestCompleteTwiceGuard:
    def test_complete_already_completed_inspection_rejected(self):
        """PRD §3.2: "An `Inspector` completes a `DRAFT` inspection of kind
        `MOVE_IN` only while its tenancy is `PENDING_MOVE_IN`; any other
        tenancy state is rejected with `ERR_INVALID_STATE_TRANSITION`".

        Completing an already-COMPLETED inspection fails; the tenancy stays
        OCCUPIED and move_in_on is unchanged.

        Design: Corner/state_machines/complete_already_completed_inspection_rejected
        """
        ctx = setup_occupied_tenancy()
        mi = ctx["move_in"]
        resp = api_client.complete_inspection(mi["id"], th.make_inspector_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        ten = get_tenancy(ctx["tenancy"]["id"])
        assert ten["status"] == "OCCUPIED"
        assert ten["move_in_on"] == "2025-01-10"


class TestKeyReturnFrozenAtVacated:
    def test_key_return_after_vacated_rejected(self):
        """PRD §3.3: "While the tenancy is `OCCUPIED` or `NOTICE_GIVEN` — and
        only then — a `PropertyManager` may record the absolute
        `keys_returned` and `fobs_returned` tallies" and "Once the tenancy
        reaches `VACATED` the books on physical returns close: the counts
        snapshotted at move-out completion are the final word for the key,
        fob, and lock charges described below."

        record_key_return in VACATED fails; the counts stay frozen.

        Design: Corner/state_machines/key_return_after_vacated_rejected
        """
        ctx = setup_vacated_tenancy(move_out_items=[], keys_returned=1,
                                    fobs_returned=0)
        ten = ctx["tenancy"]
        assert ten["status"] == "VACATED"
        resp = api_client.record_key_return(
            ten["id"], {"keys_returned": 2, "fobs_returned": 1}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        ten_after = get_tenancy(ten["id"])
        assert ten_after["keys_returned"] == 1
        assert ten_after["fobs_returned"] == 0
