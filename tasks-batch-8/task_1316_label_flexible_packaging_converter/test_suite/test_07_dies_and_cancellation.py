"""Die tooling-charge billing variants, cancellation's compensating release,
and the artwork-supersession cascade."""
from test_helpers import (
    EST,
    PREPRESS,
    api_client,
    approve_job,
    create_customer,
    create_ink_recipe,
    create_job_for,
    create_press,
    create_purchased_die,
    create_shelf_die,
    create_substrate,
    current_artwork_version,
    get_die,
    get_job,
    job_chain,
    register_artwork,
    release_job,
    setup_plant,
    validate_success,
)


class TestDieChargeVariants:

    def test_purchased_die_bills_first_released_job(self):
        """PRD §3.2: "A die ordered from the toolmaker through the new-die
        purchase capability also starts `ACTIVE` with `charge_collected` false,
        but it carries a one-time tooling charge of 750,000 cents (that is,
        $7,500.00) in `new_die_charge_cents`."
        PRD §3.5: "If the referenced die carries a positive
        `new_die_charge_cents` and its `charge_collected` is still false, the
        full tooling charge is billed into this job as
        `die_charge_applied_cents`, the die's `charge_collected` flips to true,
        and the die's `version` increments."

        Design: Difficulty/dual_variant_calc/die_charge_purchase_vs_shelf_variants
        """
        chain = job_chain(stop_at="RELEASED", account_name="Beta Pack P",
                          artwork_code="AW-2P", substrate_code="PET-12P",
                          recipe_code="INK-2P", die_mode="purchase",
                          die_code="D-P", press_code="P-2P",
                          quantity_ordered=1000)
        job = chain["job"]
        die = get_die(chain["plant"]["die"]["id"])
        assert die["new_die_charge_cents"] == 750000
        assert job["die_charge_applied_cents"] == 750000, \
            "the first released job absorbs the full tooling charge"
        assert die["charge_collected"] is True

    def test_shelf_die_bills_nothing(self):
        """PRD §3.2: "A die already on the shelf is simply registered: it
        starts `ACTIVE`, its `new_die_charge_cents` is 0, and its
        `charge_collected` is false."
        PRD §3.5: "A job that releases against a die whose charge was already
        collected — or that never carried a charge — leaves its
        `die_charge_applied_cents` at 0."

        Design: Difficulty/dual_variant_calc/die_charge_purchase_vs_shelf_variants
        """
        chain = job_chain(stop_at="RELEASED", account_name="Beta Pack S",
                          artwork_code="AW-2S", substrate_code="PET-12S",
                          recipe_code="INK-2S", die_mode="shelf",
                          die_code="D-S", press_code="P-2S",
                          quantity_ordered=1000)
        job = chain["job"]
        die = get_die(chain["plant"]["die"]["id"])
        assert die["new_die_charge_cents"] == 0
        assert job["die_charge_applied_cents"] == 0
        assert die["charge_collected"] is False


class TestCancelForkAndCompensation:

    def _two_job_fork(self, account_name: str):
        """Purchased die; job A released (bills the die), job A cancelled,
        job B created. Returns (plant, job_a_id, job_b_id)."""
        plant = setup_plant(account_name=account_name, artwork_code="AW-6",
                            substrate_code="BOPP-32", recipe_code="INK-6",
                            die_mode="purchase", die_code="D-F",
                            press_code="P-6")
        plant["cfg"] = {}
        j_a = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        approve_job(j_a["id"])
        release_job(j_a["id"], current_artwork_version(plant))
        return plant, j_a["id"]

    def test_cancel_from_released_releases_die_charge(self):
        """PRD §3.8: "Cancellation is compensating, not merely terminal. If the
        cancelled job had billed the die tooling charge and is still the die's
        billing job, the die's `charge_collected` flips back to false and the
        job's `die_charge_applied_cents` is released, so that the next job
        released against that die is billed instead."
        PRD §3.8: "Until a job goes on press, an `Estimator` may cancel it:
        cancellation is permitted from `QUOTED`, `APPROVED` or `RELEASED`, and
        from any other state it is rejected with `ERR_JOB_NOT_CANCELLABLE`."

        Design: Difficulty/compensating_invariant/die_charge_collected_flag_conserved_over_cancel
        """
        plant, j_a = self._two_job_fork("Invariant A")
        released = get_job(j_a)
        assert released["die_charge_applied_cents"] == 750000
        assert get_die(plant["die"]["id"])["charge_collected"] is True

        cancelled = validate_success(api_client.cancel_job(j_a, EST))
        assert cancelled["status"] == "CANCELLED"
        assert get_die(plant["die"]["id"])["charge_collected"] is False, (
            "after release+cancel the die's billing state equals its "
            "pre-release state exactly")

    def test_next_job_rebills_after_cancel(self):
        """PRD §3.2: "The tooling charge follows the die, not the customer. It
        is billed exactly once — into the first job released against the die —
        and if that job is later cancelled, whether explicitly or through
        artwork supersession, `charge_collected` flips back to false so that
        the next job to release against the die is billed instead."

        Design: Difficulty/compensating_invariant/die_charge_collected_flag_conserved_over_cancel
        """
        plant, j_a = self._two_job_fork("Invariant A Rebill")
        validate_success(api_client.cancel_job(j_a, EST))
        assert get_die(plant["die"]["id"])["charge_collected"] is False

        j_b = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        approve_job(j_b["id"])
        released_b = release_job(j_b["id"], current_artwork_version(plant))
        assert released_b["status"] == "RELEASED"
        assert released_b["die_charge_applied_cents"] == 750000
        assert get_die(plant["die"]["id"])["charge_collected"] is True

    def test_released_branch_cancel_vs_forward_paths(self):
        """PRD §3.8: "Until a job goes on press, an `Estimator` may cancel it:
        cancellation is permitted from `QUOTED`, `APPROVED` or `RELEASED`, and
        from any other state it is rejected with `ERR_JOB_NOT_CANCELLABLE`."
        PRD §3.2: "The tooling charge follows the die, not the customer. It is
        billed exactly once — into the first job released against the die — and
        if that job is later cancelled, whether explicitly or through artwork
        supersession, `charge_collected` flips back to false so that the next
        job to release against the die is billed instead."

        Design: Difficulty/non_linear_state_machine/labeljob_branching_cancel_vs_forward_paths
        """
        plant, j_a = self._two_job_fork("Fork Ltd")
        cancelled_a = validate_success(api_client.cancel_job(j_a, EST))
        assert cancelled_a["status"] == "CANCELLED"

        j_b = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        approve_job(j_b["id"])
        released_b = release_job(j_b["id"], current_artwork_version(plant))
        assert get_job(j_a)["status"] == "CANCELLED"
        assert released_b["status"] == "RELEASED"
        assert released_b["die_charge_applied_cents"] == 750000

    def test_one_billing_job_per_die_at_any_time(self):
        """PRD §3.2: "The tooling charge follows the die, not the customer. It
        is billed exactly once — into the first job released against the die —
        and if that job is later cancelled, whether explicitly or through
        artwork supersession, `charge_collected` flips back to false so that
        the next job to release against the die is billed instead."

        Design: Difficulty/non_linear_state_machine/labeljob_branching_cancel_vs_forward_paths
        """
        plant, j_a = self._two_job_fork("Fork Ltd 2")
        validate_success(api_client.cancel_job(j_a, EST))
        j_b = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        approve_job(j_b["id"])
        release_job(j_b["id"], current_artwork_version(plant))

        die = get_die(plant["die"]["id"])
        assert die["charge_collected"] is True, \
            "exactly one billing job per die at any time"
        assert get_job(j_a)["status"] == "CANCELLED"
        assert get_job(j_b["id"])["die_charge_applied_cents"] == 750000


class TestArtworkSupersessionCascade:

    def _cascade_setup(self, account_name: str):
        """rev1 APPROVED, rev2 SUBMITTED, purchased die, job RELEASED against
        rev1 (die billed). Returns (customer, rev1, rev2, die, job)."""
        customer = create_customer(account_name=account_name)
        rev1 = register_artwork(customer["id"], artwork_code="AW-7",
                                revision_no=1, color_count=2,
                                plate_set_cost_cents=120000)
        rev2 = register_artwork(customer["id"], approve=False,
                                artwork_code="AW-7", revision_no=2,
                                color_count=2, plate_set_cost_cents=130000)
        substrate = create_substrate(substrate_code="BOPP-33")
        ink = create_ink_recipe(recipe_code="INK-7")
        die = create_purchased_die(die_code="D-C", shape_description="hex",
                                   cavities_across=2)
        press = create_press(press_code="P-7")
        plant = {"customer": customer, "artwork": rev1, "substrate": substrate,
                 "ink": ink, "die": die, "press": press, "cfg": {}}
        job = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        approve_job(job["id"])
        release_job(job["id"], current_artwork_version(plant))
        return customer, rev1, rev2, die, job

    def test_approving_newer_revision_supersedes_prior(self):
        """PRD §3.3: "Approval is a supersession event. Any other revision of
        the same customer and `artwork_code` that is currently `APPROVED` flips
        automatically to `OBSOLETE`, so that at most one revision of a code is
        ever approved at a time."

        Design: Difficulty/transitive_cascade/artwork_approval_supersede_cancels_job_releases_die
        """
        customer, rev1, rev2, die, job = self._cascade_setup("Cascade SA")

        approved2 = validate_success(
            api_client.approve_artwork(customer["id"], rev2["id"], PREPRESS))
        assert approved2["status"] == "APPROVED"

        rev1_after = validate_success(api_client.get_artwork_version(
            customer["id"], rev1["id"], PREPRESS))
        assert rev1_after["status"] == "OBSOLETE", \
            "the previously approved revision flips to OBSOLETE"

    def test_supersession_cancels_open_job_and_releases_die(self):
        """PRD §3.3: "The cascade continues into the order book: every job in
        `QUOTED`, `APPROVED` or `RELEASED` that still references the
        now-`OBSOLETE` revision flips to `CANCELLED`, and if such a job had
        collected the die tooling charge, that charge is released — the die's
        `charge_collected` returns to false, freeing the charge to be billed to
        the next job that uses the die."
        PRD §3.8: "The identical compensating release applies when cancellation
        is automatic — a job cancelled because its referenced artwork revision
        was superseded returns its die to the un-billed state in exactly the
        same way."

        Design: Difficulty/transitive_cascade/artwork_approval_supersede_cancels_job_releases_die
        """
        customer, rev1, rev2, die, job = self._cascade_setup("Cascade SA 2")
        pre = get_job(job["id"])
        assert pre["status"] == "RELEASED"
        assert pre["die_charge_applied_cents"] == 750000
        assert get_die(die["id"])["charge_collected"] is True

        validate_success(
            api_client.approve_artwork(customer["id"], rev2["id"], PREPRESS))

        job_after = get_job(job["id"])
        assert job_after["status"] == "CANCELLED", \
            "the RELEASED job referencing the superseded revision is cancelled"
        die_after = get_die(die["id"])
        assert die_after["charge_collected"] is False, \
            "the cascaded cancel releases the die's tooling charge"
