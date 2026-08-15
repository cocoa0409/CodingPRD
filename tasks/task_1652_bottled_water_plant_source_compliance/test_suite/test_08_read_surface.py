"""The read surface: every list and single-read endpoint answers with the
envelope contract and echoes the fixture's entities."""
import pytest

from test_helpers import (
    create_bottle,
    create_bottling_line,
    create_permit,
    create_plant,
    create_community_report_payload,
    create_preform_delivery_payload,
    create_treatment_run,
    create_wash_batch,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, SOURCE_MONITOR, COMPLIANCE_OFFICER, PL1, QA1, SL1,
)


class TestListAndReadSurfaceSweep:
    def test_list_and_read_surface_sweep(self, api):
        """PRD §2.2: "The `data` field contains the resource object or an
        array of resource objects" and "Pagination-related fields in `meta`
        (`limit`, `offset`, `total_count`, `has_more`) are included for list
        endpoints"; PRD §4 lists the filtered-list GETs for permits, bottling
        lines, preform deliveries, recalls, wash batches, treatment runs,
        bottles, and community reports.

        Design: Corner/endpoints/list_and_read_surface_sweep
        """
        plant = create_plant("Plant EP5")
        permit = create_permit(plant["id"], permit_number="SP-EP5")
        line = create_bottling_line(plant["id"])
        del_payload = create_preform_delivery_payload(delivered_units=500)
        del_payload["expected_line_version"] = line["version"]
        delivery = validate_success(api.create_preform_delivery(
            line["id"], del_payload, PL1
        ), expected_status=201)
        batch = create_wash_batch(plant["id"])
        bottle = create_bottle(plant["id"], "B-EP5")
        report = validate_success(api.create_community_report(
            plant["id"], create_community_report_payload(period_year=2026, period_month=8),
            COMPLIANCE_OFFICER,
        ), expected_status=201)
        run = create_treatment_run(plant["id"], permit["id"])

        # Filtered-list GETs (cross-plant, §4).
        permits, meta = validate_paginated(api.list_permits(
            SOURCE_MONITOR, params={"plant_id": plant["id"]}
        ))
        assert meta["total_count"] == 1 and permits[0]["id"] == permit["id"]

        plant_permits, meta = validate_paginated(api.list_plant_permits(
            plant["id"], SOURCE_MONITOR
        ))
        assert meta["total_count"] == 1 and plant_permits[0]["id"] == permit["id"]

        lines, meta = validate_paginated(api.list_bottling_lines(
            PL1, params={"plant_id": plant["id"]}
        ))
        assert meta["total_count"] == 1 and lines[0]["id"] == line["id"]

        deliveries, meta = validate_paginated(api.list_preform_deliveries(
            PL1, params={"line_id": line["id"]}
        ))
        assert meta["total_count"] == 1 and deliveries[0]["id"] == delivery["id"]

        delivery_read = validate_success(api.get_preform_delivery(delivery["id"], PL1))
        assert delivery_read["id"] == delivery["id"]

        line_deliveries, meta = validate_paginated(api.list_line_preform_deliveries(
            line["id"], PL1
        ))
        assert meta["total_count"] == 1 and line_deliveries[0]["id"] == delivery["id"]

        # No recalls exist; empty collections are well-formed.
        _recalls, meta = validate_paginated(api.list_recalls(
            COMPLIANCE_OFFICER, params={"plant_id": plant["id"]}
        ))
        assert meta["total_count"] == 0 and meta["has_more"] is False
        _plant_recalls, meta = validate_paginated(api.list_plant_recalls(
            plant["id"], COMPLIANCE_OFFICER
        ))
        assert meta["total_count"] == 0 and meta["has_more"] is False

        batches, meta = validate_paginated(api.list_wash_batches(
            SL1, params={"plant_id": plant["id"], "washer_unit": "WASHER_A"}
        ))
        assert meta["total_count"] == 1 and batches[0]["id"] == batch["id"]

        plant_batches, meta = validate_paginated(api.list_plant_wash_batches(
            plant["id"], SL1
        ))
        assert meta["total_count"] == 1 and plant_batches[0]["id"] == batch["id"]

        batch_read = validate_success(api.get_wash_batch(batch["id"], SL1))
        assert batch_read["id"] == batch["id"]

        runs, meta = validate_paginated(api.list_treatment_runs(
            QA1, params={"plant_id": plant["id"], "status": "SCHEDULED"}
        ))
        assert meta["total_count"] == 1 and runs[0]["id"] == run["id"]

        bottles, meta = validate_paginated(api.list_bottles(
            SL1, params={"plant_id": plant["id"], "status": "SANITIZED"}
        ))
        assert meta["total_count"] == 1 and bottles[0]["id"] == bottle["id"]

        reports, meta = validate_paginated(api.list_community_reports(
            COMPLIANCE_OFFICER, params={"plant_id": plant["id"], "status": "DRAFT"}
        ))
        assert meta["total_count"] == 1 and reports[0]["id"] == report["id"]

        # Single-read endpoints echo their entity.
        assert validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))["id"] == permit["id"]
        assert validate_success(api.get_bottling_line(line["id"], PL1))["id"] == line["id"]
        assert validate_success(api.get_treatment_run(run["id"], QA1))["id"] == run["id"]
        assert validate_success(api.get_bottle(bottle["id"], SL1))["id"] == bottle["id"]
        assert validate_success(api.get_community_report(report["id"], COMPLIANCE_OFFICER))["id"] == report["id"]
