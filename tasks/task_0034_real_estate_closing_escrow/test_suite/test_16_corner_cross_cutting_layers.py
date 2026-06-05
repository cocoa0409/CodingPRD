"""Corner section: cross_cutting_complexity_layers — OCC stale-version on
CD create, the scheduled exchange-account FAILED transition on read after
clock advance, and the under-contract terminate cascading-side-effects.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_actors,
    setup_active_agreement,
    setup_under_contract_agreement,
    create_exchange_account,
    create_closing_disclosure_payload,
    create_deposit,
    confirm_deposit,
    create_title_search,
    complete_title_search,
    setup_locked_wire,
    advance_clock,
    terminate_purchase_agreement_payload,
    api_client,
)


class TestOccAgreementStaleVersionOnCdCreate:
    def test_cd_create_with_stale_expected_agreement_version_returns_412(self, api):
        """PRD §2.7: "Creating a new ``ClosingDisclosure`` requires the request body to carry ``expected_agreement_version``, an integer the client last observed on the target ``PurchaseAgreement``. If that value does not equal the agreement's current ``version``, the request is rejected with ``ERR_STALE_AGREEMENT_VERSION`` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_agreement_stale_version_on_cd_create
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_under_contract_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        current_version = base["agreement_version"]
        # Send a stale expected version (one below current).
        res = api.create_closing_disclosure(
            create_closing_disclosure_payload(
                agreement_id=base["agreement_id"],
                expected_agreement_version=current_version - 1,
            ),
            base["actors"]["eo"],
        )
        validate_error(res, "ERR_STALE_AGREEMENT_VERSION", expected_status=412)


class TestScheduledExchangeAccountFailedOnClockAdvance:
    def test_open_exchange_flips_failed_when_clock_past_identification_deadline(self, api):
        """PRD §3.7: "Two automatic transitions to ``FAILED`` also exist, each evaluated synchronously when the system observes the relevant deadline (typically on a read or a related write). From ``OPEN``, the account flips to ``FAILED`` when the current UTC clock is strictly greater than ``identification_deadline`` and ``replacement_property_identified`` is still ``false`` — no replacement was identified in time."

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_exchange_account_deadline_failed_on_clock_advance
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        ea = create_exchange_account(
            actors, relinquished_closing_date="2026-06-01T00:00:00Z"
        )
        # Advance clock by 46 days (3_974_400 seconds) — past the 45-day
        # identification deadline; replacement_property_identified is still false.
        advance_clock(3_974_400, actors["co"])
        res = api.get_exchange_account(ea["id"], actors["eo"])
        observed = validate_success(res, expected_status=200)
        assert observed["status"] == "FAILED", \
            f"OPEN exchange must lazy-flip to FAILED after identification deadline, got {observed['status']}"


class TestCascadingSideEffectsTerminateUnderContractWithMaterialDefect:
    def test_terminate_under_contract_cascade_emd_escrow_agreement(self, api):
        """PRD §3.6: "From ``UNDER_CONTRACT``, termination is reserved for the unresolved-material-defect scenario: the agreement's ``TitleSearch`` must currently carry ``has_material_defect`` of ``true``."
        PRD §3.6: "The ``terminated_reason`` must again be non-empty. The compensating action flips every ``CONFIRMED`` earnest money deposit to ``REFUNDED`` (this is the buyer-protection clause: confirmed deposits return to the buyer once a material defect blocks the deal), transitions the escrow from ``FUNDED`` to ``CLOSED``, and bumps both versions."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_terminate_under_contract_with_material_defect
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_under_contract_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        # Title work with a MATERIAL defect, NOT resolved → has_material_defect=true.
        search = create_title_search(base["actors"], base["agreement_id"])
        complete_title_search(
            base["actors"], search["id"],
            defects=[{
                "kind": "lien",
                "severity": "MATERIAL",
                "description": "Unpaid lien.",
            }],
        )
        # BUYER wire LOCKED so refunds can route per PRD §3.6.
        setup_locked_wire(
            base["actors"], base["agreement_id"], party="BUYER",
            voice_callback_reference="VC-CSE",
        )
        res = api.terminate_purchase_agreement(
            base["agreement_id"],
            terminate_purchase_agreement_payload(
                terminated_reason="Title material defect could not be resolved.",
            ),
            base["actors"]["eo"],
        )
        agr_after = validate_success(res, expected_status=200)
        assert agr_after["status"] == "TERMINATED"

        emd_after = validate_success(
            api.get_earnest_money_deposit(base["deposit_id"], base["actors"]["eo"]),
            expected_status=200,
        )
        assert emd_after["status"] == "REFUNDED", \
            f"CONFIRMED deposit must flip to REFUNDED on UNDER_CONTRACT→TERMINATED, got {emd_after['status']}"

        esc_after = validate_success(
            api.get_escrow_account(base["escrow_id"], base["actors"]["eo"]),
            expected_status=200,
        )
        assert esc_after["status"] == "CLOSED", \
            f"escrow must flip to CLOSED on UNDER_CONTRACT→TERMINATED, got {esc_after['status']}"
