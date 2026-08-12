"""Reverse reachability of the cascade-created RebuildProject through the
filtered projects list."""

import test_helpers as fx
from test_helpers import (
    PM,
    validate_paginated,
    validate_success,
)

ASSESSOR_1 = "assessor-1"


def test_fk_reverse_discovery_of_cascade_created_project(api):
    """PRD §3.2: "Acceptance moves the assessment to the terminal `ACCEPTED`, moves the machine to `ASSESSED`, and — critically — auto-creates the RebuildProject that will carry the engagement: the project is born with `work_status` of `SCOPED`, `commercial_status` of `QUOTE_DRAFT`, `decision` of `NONE`, and its `assessment_id`, `machine_id`, and `customer_id` all linked from the accepted assessment and its machine."
    PRD §3.3: "Projects can be listed with optional `machine_id`, `customer_id`, and `assessment_id` filters."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/endpoints/fk_reverse_discovery_of_cascade_created_project
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])
    assessment = fx.create_assessment(machine["id"], assessor_id=ASSESSOR_1)
    fx.submit_assessment(assessment["id"], assessor_id=ASSESSOR_1)

    # Accept returns the updated Assessment resource, not the created project.
    accepted = validate_success(api.accept_assessment(assessment["id"], PM), 200)
    assert accepted["id"] == assessment["id"]
    assert accepted["status"] == "ACCEPTED"
    fx.assert_assessment(accepted)

    # The cascade-created project is discoverable via the assessment_id filter.
    data, meta = validate_paginated(
        api.list_projects(PM, params={"assessment_id": assessment["id"]})
    )
    assert meta["total_count"] == 1
    project = data[0]
    assert project["work_status"] == "SCOPED"
    assert project["commercial_status"] == "QUOTE_DRAFT"
    assert project["decision"] == "NONE"
    assert project["assessment_id"] == assessment["id"]
    assert project["machine_id"] == machine["id"]
    assert project["customer_id"] == customer["id"]
    fx.assert_project(project)
