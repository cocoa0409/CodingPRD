"""Colony sterilization rate: resident basis and monitoring posture derivation."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    make_coordinator_headers,
    setup_caretaker_with_colony, create_cat, create_partner_clinic,
    create_clinic_day, list_slots, get_colony, get_cat, create_foster_home,
    create_foster_placement_payload, drive_cat_to_post_surgery,
)


def _drive_to_post_surgery_and_decide(api, cat, cth, day_id, slot, pathway):
    """Surgery then pathway decision. Returns the cat dict after the decision."""
    _, _, cat_after = drive_cat_to_post_surgery(
        cat, cth, day_id, slot, trap_date="2026-08-19T00:00:00Z")
    ch = make_coordinator_headers()
    return validate_success(api.decide_pathway(
        cat_after["id"],
        {"pathway": pathway, "expected_cat_version": cat_after["version"]}, ch))


class TestResidentBasisExcludesAdopted:
    """Difficulty/dual_variant_calc/colony_sterilization_resident_basis_excludes_adopted"""

    def _build_scenario(self, api):
        """Colony of 4: 2 RETURNED, 1 kitten IN_FOSTER, 1 ADOPTED."""
        ct, cth, col = setup_caretaker_with_colony(estimated_population=4)
        c1 = create_cat(col, intake_tag="C1", approximate_age_months=20)
        c2 = create_cat(col, intake_tag="C2", sex="FEMALE", approximate_age_months=22)
        k1 = create_cat(col, intake_tag="K1", sex="FEMALE", approximate_age_months=2)
        c3 = create_cat(col, intake_tag="C3", approximate_age_months=18)
        clinic = create_partner_clinic(name="BayVet")
        day = create_clinic_day(clinic, service_date="2026-08-20T00:00:00Z",
                                base_capacity=10, surge_capacity=0)
        slots = list_slots(day)
        ch = make_coordinator_headers()

        # Two adults returned to the field (sterilized).
        _drive_to_post_surgery_and_decide(api, c1, cth, day["id"], slots[0],
                                          "RETURN_TO_FIELD")
        _drive_to_post_surgery_and_decide(api, c2, cth, day["id"], slots[1],
                                          "RETURN_TO_FIELD")

        # Kitten into foster care (resident denominator only).
        _, _, k1_after = drive_cat_to_post_surgery(
            k1, cth, day["id"], slots[2], trap_date="2026-08-19T00:00:00Z")
        home, vh = create_foster_home(capacity_kittens=3)
        get_success_data(api.create_foster_placement(
            create_foster_placement_payload(k1_after["id"], home["id"]), ch))

        # Adult adopted (leaves the resident set entirely).
        adopted = _drive_to_post_surgery_and_decide(api, c3, cth, day["id"], slots[3],
                                                    "ADOPTION")
        get_success_data(api.finalize_adoption(adopted["id"], ch))
        return col

    def test_adopted_cat_excluded_from_denominator(self, api):
        """PRD §2.6: "The resident set comprises the colony's cats standing in any
        of `AT_LARGE`, `TRAPPED`, `AT_CLINIC`, `POST_SURGERY`, `RETURNED`,
        `COLONY_STERILIZED`, `IN_FOSTER`, or `ADOPTION_PIPELINE`; cats that are
        `ADOPTED` or `DECEASED` leave the resident set entirely."
        PRD §2.6: "The fraction is rounded half-up to four decimal places."

        Design: Difficulty/dual_variant_calc/colony_sterilization_resident_basis_excludes_adopted
        """
        col = self._build_scenario(api)
        colony = get_colony(col["id"])
        assert colony["sterilized_pct"] == pytest.approx(0.6667, abs=0.00001), \
            (f"2 sterilized of 3 residents (ADOPTED excluded, IN_FOSTER in "
             f"denominator only), got {colony['sterilized_pct']}")

    def test_posture_active_below_threshold(self, api):
        """PRD §2.6: "A colony is `STABLE` when its sterilized fraction is at
        least 0.75 and no complaint against it stands `OPEN`. ... In every other
        case the colony is `ACTIVE`, which is also its posture at registration."
        PRD §2.6: "Because `IN_FOSTER` and `ADOPTION_PIPELINE` cats sit in the
        denominator but never the numerator, kittens awaiting adoption depress the
        rate until they resolve."

        Design: Difficulty/dual_variant_calc/colony_sterilization_resident_basis_excludes_adopted
        """
        col = self._build_scenario(api)
        colony = get_colony(col["id"])
        assert colony["sterilized_pct"] == pytest.approx(0.6667, abs=0.00001)
        assert colony["monitoring_status"] == "ACTIVE", \
            f"0.6667 is below the 0.75 threshold; got {colony['monitoring_status']}"
