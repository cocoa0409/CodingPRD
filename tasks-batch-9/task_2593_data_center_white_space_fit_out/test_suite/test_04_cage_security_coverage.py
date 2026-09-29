"""Cage coverage arithmetic: the empty active-camera set, the inclusive requirement
edge and the cap at full coverage."""
import pytest

from test_helpers.fixtures import (
    commission_device,
    create_cage,
    create_camera,
    create_card_reader,
    create_tenant,
    read_cage,
    read_device,
    setup_planning_hall,
)


class TestCageCoverageBoundaries:
    """Coverage is a set-summed ratio over ACTIVE cameras only, capped at 100.00."""

    def _cage_with_planned_hardware(self):
        tenant = create_tenant("TN-N1", contracted_kw=100.00)
        ctx = setup_planning_hall("HN1", tenant_mode="MULTI_TENANT")
        cage = create_cage(
            ctx["hall_id"], tenant["id"], "CG-1", perimeter_length_m=40.0
        )
        ctx["tenant"] = tenant
        ctx["cage"] = cage
        ctx["cam_1"] = create_camera(cage["id"], "CAM-1", 38.0)
        ctx["rdr_n"] = create_card_reader(cage["id"], "RDR-N", "Z-N")
        ctx["rdr_s"] = create_card_reader(cage["id"], "RDR-S", "Z-S")
        return ctx

    def test_planned_cameras_leave_coverage_at_zero_until_commissioned(self):
        """With both readers ACTIVE and the only camera still PLANNED the cage reports
        0.00 coverage and stays at FIT_OUT; commissioning that camera takes it to
        exactly 95.00, which satisfies the 95.00 requirement inclusively.

        PRD: "Every device starts at `PLANNED` and, crucially, contributes nothing at
        all to coverage while it is there — an installed but uncommissioned camera
        leaves coverage at 0.00."

        Design: Difficulty/boundary_precision_check/cage_camera_coverage_empty_device_set_yields_zero_pct
        """
        ctx = self._cage_with_planned_hardware()
        commission_device(ctx["rdr_n"]["id"])
        commission_device(ctx["rdr_s"]["id"])

        before = read_cage(ctx["cage"]["id"])
        assert before["camera_coverage_pct"] == pytest.approx(0.00, abs=0.005), (
            "an empty ACTIVE camera set yields 0.00, not a division by zero"
        )
        assert before["active_reader_zone_count"] == 2
        assert before["operational_status"] == "FIT_OUT", (
            "the reader requirement alone does not secure the cage"
        )

        commission_device(ctx["cam_1"]["id"])
        at_boundary = read_cage(ctx["cage"]["id"])
        assert at_boundary["camera_coverage_pct"] == pytest.approx(95.00, abs=0.005), (
            "38.0 metres seen of a 40.0 metre perimeter is 95.00 percent"
        )
        assert at_boundary["operational_status"] == "SECURED", (
            "a cage measuring exactly 95.00 against a 95.00 requirement satisfies it"
        )

    def test_overlapping_camera_fields_are_capped_at_full_coverage(self):
        """A second 10.0 metre camera would raise the raw ratio to 120.00 percent; the
        published figure is capped at 100.00 and the cage stays SECURED.

        PRD: "multiplied by 100, capped at 100.00 so that overlapping camera fields
        cannot report more than full coverage, and rounded to two decimal places."

        Design: Difficulty/boundary_precision_check/cage_camera_coverage_empty_device_set_yields_zero_pct
        """
        ctx = self._cage_with_planned_hardware()
        commission_device(ctx["rdr_n"]["id"])
        commission_device(ctx["rdr_s"]["id"])
        commission_device(ctx["cam_1"]["id"])

        cam_2 = create_camera(ctx["cage"]["id"], "CAM-2", 10.0)
        commission_device(cam_2["id"])

        cage = read_cage(ctx["cage"]["id"])
        assert cage["camera_coverage_pct"] == pytest.approx(100.00, abs=0.005), (
            "48.0 metres of field over a 40.0 metre perimeter caps at 100.00"
        )
        assert cage["active_reader_zone_count"] == 2
        assert cage["operational_status"] == "SECURED"
        assert read_device(ctx["cam_1"]["id"])["status"] == "ACTIVE"
        assert read_device(cam_2["id"])["status"] == "ACTIVE"

    def test_two_readers_on_one_zone_count_once(self):
        """The reader figure counts distinct zone labels, so a cage whose only two
        ACTIVE readers arm the same zone reports one zone and stays at FIT_OUT even at
        full camera coverage.

        PRD: "`active_reader_zone_count` is the number of **distinct**
        `reader_zone_label` values among the cage's `ACTIVE` card readers — two readers
        arming the same zone count once."

        Design: Difficulty/boundary_precision_check/cage_camera_coverage_empty_device_set_yields_zero_pct
        """
        tenant = create_tenant("TN-N2", contracted_kw=100.00)
        ctx = setup_planning_hall("HN2", tenant_mode="MULTI_TENANT")
        cage = create_cage(
            ctx["hall_id"], tenant["id"], "CG-2", perimeter_length_m=40.0
        )
        camera = create_camera(cage["id"], "CAM-1", 40.0)
        first = create_card_reader(cage["id"], "RDR-N", "Z-N")
        second = create_card_reader(cage["id"], "RDR-N2", "Z-N")
        commission_device(camera["id"])
        commission_device(first["id"])
        commission_device(second["id"])

        read = read_cage(cage["id"])
        assert read["camera_coverage_pct"] == pytest.approx(100.00, abs=0.005)
        assert read["active_reader_zone_count"] == 1, (
            "both readers arm zone Z-N, so the distinct count is one"
        )
        assert read["operational_status"] == "FIT_OUT", (
            "one distinct zone falls short of the default requirement of two"
        )
