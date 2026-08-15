"""Currency translation variants, minority interest split, and consolidation."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_entity_payload, create_journal_entry_payload, create_fx_rate_payload,
    set_clock, create_period, create_entity, open_period, get_entity_period_for,
    setup_open_period_with_entity, post_je, register_identity_fx_rate,
    drive_entity_period_to_subledger_cut, drive_entity_period_to_reconciled,
    CONTROLLER, PREPARER, APPROVER,
)
from test_helpers import api_client


def _setup_two_entities_period():
    """Period P1 with two EUR-functional entities: one CURRENT_RATE, one TEMPORAL."""
    set_clock("2026-01-15T00:00:00Z")
    period = create_period()
    ent_cur = create_entity(entity_code="EUCUR", name="EU Current",
                             functional_currency="EUR", ownership_pct=100,
                             translation_method="CURRENT_RATE")
    ent_tmp = create_entity(entity_code="EUTMP", name="EU Temporal",
                             functional_currency="EUR", ownership_pct=100,
                             translation_method="TEMPORAL")
    open_period(period["id"])
    ep_cur = get_entity_period_for(period["id"], ent_cur["id"])
    ep_tmp = get_entity_period_for(period["id"], ent_tmp["id"])
    # Post a balanced JE on each (a balanced entry nets to zero under the
    # PRD §3.5 signed trial-balance sum, so trial_balance stays 0)
    post_je(ep_cur["id"], 1000000, currency="EUR")
    post_je(ep_tmp["id"], 1000000, currency="EUR")
    # FX rates
    register_identity_fx_rate(period["id"], from_ccy="EUR", to_ccy="USD",
                               rate_kind="PERIOD_END", rate=1.10)
    register_identity_fx_rate(period["id"], from_ccy="EUR", to_ccy="USD",
                               rate_kind="AVERAGE", rate=1.05)
    register_identity_fx_rate(period["id"], from_ccy="EUR", to_ccy="USD",
                               rate_kind="HISTORICAL", rate=1.02)
    return period, ent_cur, ent_tmp, ep_cur, ep_tmp


class TestCurrencyTranslationVariants:
    def test_temporal_translation_forces_cta_zero(self, api):
        """PRD §3.7: "Under the temporal method `cta_minor` is forced to exactly
        zero, because temporal remeasurement hits profit and loss rather than
        equity".

        Design: Difficulty/dual_variant_calc/currency_translation_current_rate_vs_temporal_cta_divergence
        """
        period, _, ent_tmp, _, ep_tmp = _setup_two_entities_period()
        get_success_data(api.translate_entity_period(ep_tmp["id"], CONTROLLER))
        ep = validate_success(api.get_entity_period(ep_tmp["id"], CONTROLLER), 200)
        assert ep["cta_minor"] == 0


class TestMinorityInterest:
    def test_minority_interest_zero_when_full_ownership(self, api):
        """PRD §3.7: "The `nci_share_minor` is the `translated_balance_minor`
        multiplied by the percentage not owned — one hundred minus
        `ownership_pct`, divided by one hundred — rounded half up to integer minor
        units, and it is exactly zero when `ownership_pct` is one hundred."

        Design: Corner/calculations/minority_interest_zero_when_full_ownership
        """
        period, entity, ep = setup_open_period_with_entity()
        post_je(ep["id"], 50000)
        register_identity_fx_rate(period["id"], from_ccy="USD", to_ccy="USD", rate=1.0)
        drive_entity_period_to_subledger_cut(ep["id"])
        get_success_data(api.translate_entity_period(ep["id"], CONTROLLER))
        get_success_data(api.mark_entity_period_reconciled(ep["id"], PREPARER))
        ready = validate_success(api.mark_entity_period_ready(ep["id"], PREPARER), 200)
        assert ready["nci_share_minor"] == 0
