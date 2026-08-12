"""Rework batch lifecycle: mass conservation across commit/scrap and the
rework class gate."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_allergen, create_line, create_product, create_run,
    create_rework_batch_payload,
    MANAGER, SUPERVISOR, OPERATOR,
)


def _rework_scenario(target_rework_class="SAME_ALLERGEN_PROFILE"):
    """Line + source product/run + target product/run; returns dict."""
    allergen = create_allergen("MILK")
    line = create_line("LINE-15", "ALLERGEN_DEDICATED")
    prod_a = create_product("P-A", ["MILK"], rework_class="SAME_ALLERGEN_PROFILE")
    prod_b = create_product("P-B", ["MILK"], rework_class=target_rework_class)
    run_src = create_run(line["id"], prod_a["id"],
                         "2026-06-14T08:00:00Z", "2026-06-14T10:00:00Z")
    run_tgt = create_run(line["id"], prod_b["id"],
                         "2026-06-14T12:00:00Z", "2026-06-14T14:00:00Z")
    return {"line": line, "prod_a": prod_a, "prod_b": prod_b,
            "run_src": run_src, "run_tgt": run_tgt}


def _create_batch(ctx, quantity_kg=100):
    res = api_client.create_rework_batch(
        create_rework_batch_payload(ctx["run_src"]["id"], ctx["prod_a"]["id"],
                                    quantity_kg=quantity_kg),
        SUPERVISOR)
    return validate_success(res, 201)


class TestReworkMassConservation:
    def test_partial_commit_then_scrap_conserves_mass(self, api):
        """PRD §3.7: "At creation the batch's `remaining_kg` is initialized to
        the full `quantity_kg`, its `rework_allergen_set` is copied from the
        source product's declared `allergen_set`, and its `status` opens at
        `AVAILABLE`."
        PRD §3.7: "A successful commit decrements `remaining_kg` by the
        committed quantity, and a batch whose remainder reaches zero flips
        automatically from `COMMITTED` to `CONSUMED` with no further client
        action."
        PRD §3.7: "A `QaSupervisor` may instead scrap a batch standing at
        `AVAILABLE` or `COMMITTED` — a batch already in a terminal state is
        rejected with `ERR_REWORK_TERMINAL` (HTTP 409) — which zeroes
        `remaining_kg` and lands the batch at `SCRAPPED`."

        Design: Difficulty/compensating_invariant/rework_mass_conservation_commit_scrap
        """
        ctx = _rework_scenario()
        batch = _create_batch(ctx, 100)
        assert batch["remaining_kg"] == 100, "remaining_kg initializes to quantity_kg"
        assert batch["status"] == "AVAILABLE"

        committed = validate_success(
            api.commit_rework_batch(batch["id"],
                                    {"target_run_id": ctx["run_tgt"]["id"],
                                     "quantity_kg": 40},
                                    OPERATOR), 200)
        assert committed["remaining_kg"] == 60, "100 - 40 committed = 60 remaining"
        assert committed["status"] == "COMMITTED"

        scrapped = validate_success(api.scrap_rework_batch(batch["id"], SUPERVISOR), 200)
        assert scrapped["remaining_kg"] == 0, "scrap zeroes remaining_kg"
        assert scrapped["status"] == "SCRAPPED"

    def test_full_commit_auto_consumes_at_zero(self, api):
        """PRD §3.7: "A successful commit decrements `remaining_kg` by the
        committed quantity, and a batch whose remainder reaches zero flips
        automatically from `COMMITTED` to `CONSUMED` with no further client
        action."

        Design: Difficulty/compensating_invariant/rework_mass_conservation_commit_scrap
        """
        ctx = _rework_scenario()
        batch = _create_batch(ctx, 100)
        consumed = validate_success(
            api.commit_rework_batch(batch["id"],
                                    {"target_run_id": ctx["run_tgt"]["id"],
                                     "quantity_kg": 100},
                                    OPERATOR), 200)
        assert consumed["remaining_kg"] == 0
        assert consumed["status"] == "CONSUMED"


class TestReworkClassGate:
    def test_no_rework_target_rejects_commit(self, api):
        """PRD §3.7: "The class gate reads the target run's product
        `rework_class`: under `SAME_INTO_SAME` the batch's source product must
        be the very product the target run is manufacturing; under
        `SAME_ALLERGEN_PROFILE` the batch's `rework_allergen_set` must be
        identical to the target product's `allergen_set`; under
        `RESTRICTED_REWORK` the batch's allergen set must be a subset of the
        target's; and under `NO_REWORK` every commit is refused."
        PRD §3.7: "A class-gate failure is rejected with
        `ERR_REWORK_CLASS_VIOLATION` (HTTP 422)."

        Design: Corner/validations/rework_class_no_rework_rejected
        """
        ctx = _rework_scenario(target_rework_class="NO_REWORK")
        batch = _create_batch(ctx, 10)
        res = api.commit_rework_batch(batch["id"],
                                      {"target_run_id": ctx["run_tgt"]["id"],
                                       "quantity_kg": 5},
                                      OPERATOR)
        validate_error(res, "ERR_REWORK_CLASS_VIOLATION")
