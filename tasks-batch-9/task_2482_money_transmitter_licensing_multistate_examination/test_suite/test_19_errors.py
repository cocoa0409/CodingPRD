"""Not-found reachability across the resource families of the licensing estate.

PRD 2.7 gives reference resolution its own rung on the evaluation ladder and
pins one error id per resource family. These tests address a well-formed UUID
that exists nowhere and check that each family answers with its own 404 rather
than with a shared generic code, both on the single-item reads and on the two
write paths that are the only way to reach a jurisdiction or a holding by id.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import factories as F
from test_helpers.test_users import MANAGER_HEADERS, OFFICER_HEADERS
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_CONTROL_PERSON_NOT_FOUND,
    ERR_DELEGATE_NOT_FOUND,
    ERR_ENFORCEMENT_NOT_FOUND,
    ERR_EXAM_NOT_FOUND,
    ERR_HOLDING_NOT_FOUND,
    ERR_INFO_REQUEST_NOT_FOUND,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_LICENSE_NOT_FOUND,
    ERR_LICENSEE_NOT_FOUND,
    ERR_TEST_NOT_FOUND,
)

# ---------------------------------------------------------------------------
# The single-item read sweep
# ---------------------------------------------------------------------------

READ_SWEEP = [
    (
        "licensee",
        lambda api: api.get_licensee(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_LICENSEE_NOT_FOUND,
    ),
    (
        "control_person",
        lambda api: api.get_control_person(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_CONTROL_PERSON_NOT_FOUND,
    ),
    (
        "license_application",
        lambda api: api.get_application(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_APPLICATION_NOT_FOUND,
    ),
    (
        "state_license",
        lambda api: api.get_state_license(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_LICENSE_NOT_FOUND,
    ),
    (
        "delegate",
        lambda api: api.get_delegate(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_DELEGATE_NOT_FOUND,
    ),
    (
        "delegate_authorization",
        lambda api: api.get_delegate_authorization(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_AUTHORIZATION_NOT_FOUND,
    ),
    (
        "permissible_investment_test",
        lambda api: api.get_investment_test(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_TEST_NOT_FOUND,
    ),
    (
        "multistate_exam",
        lambda api: api.get_exam(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_EXAM_NOT_FOUND,
    ),
    (
        "information_request",
        lambda api: api.get_information_request(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_INFO_REQUEST_NOT_FOUND,
    ),
    (
        "enforcement_action",
        lambda api: api.get_enforcement_action(NON_EXISTENT_UUID, MANAGER_HEADERS),
        ERR_ENFORCEMENT_NOT_FOUND,
    ),
]


@pytest.mark.parametrize(
    "read_call, expected_error_id",
    [(call, error_id) for _family, call, error_id in READ_SWEEP],
    ids=[family for family, _call, _error_id in READ_SWEEP],
)
def test_unknown_id_on_a_single_item_read_returns_that_family_s_own_not_found(
    api: MoneyTransmitterApiClient, read_call, expected_error_id: str
) -> None:
    """Against an empty database one absent UUID yields ten different 404 error ids, one per resource family, because the acting role is authorized on every one of these reads so the existence rung is the only rung that can fail.

    PRD 2.7: "**Reference resolution**, left to right along the path and then through the body, in this exact sequence: licensee references (`ERR_LICENSEE_NOT_FOUND`), then jurisdiction references (`ERR_JURISDICTION_NOT_FOUND`), then control-person references including `parent_control_person_id` (`ERR_CONTROL_PERSON_NOT_FOUND`), then application references (`ERR_APPLICATION_NOT_FOUND`), then state-licence references whether in the path or in a body field (`ERR_LICENSE_NOT_FOUND`), then delegate references (`ERR_DELEGATE_NOT_FOUND`), then delegate-authorization references (`ERR_AUTHORIZATION_NOT_FOUND`), then investment-holding references (`ERR_HOLDING_NOT_FOUND`), then coverage-test references (`ERR_TEST_NOT_FOUND`), then examination references including `exam_id` and `originating_exam_id` (`ERR_EXAM_NOT_FOUND`), then information-request references (`ERR_INFO_REQUEST_NOT_FOUND`), then enforcement-action references (`ERR_ENFORCEMENT_NOT_FOUND`)."
    PRD 2.7: "Because reference resolution precedes state admissibility, an operation on a non-existent licence reports the missing licence rather than an invalid state."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/unknown_ids_on_every_read_endpoint_return_not_found
    """
    validate_error(read_call(api), expected_error_id)


# ---------------------------------------------------------------------------
# The write-path foreign keys with no single-item read of their own
# ---------------------------------------------------------------------------


def test_unknown_jurisdiction_id_in_an_application_body_returns_jurisdiction_not_found(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """An application body naming a real licensee and an absent jurisdiction reports the jurisdiction, since the licensee reference resolves first and no application row is created.

    PRD 2.7: "**Reference resolution**, left to right along the path and then through the body, in this exact sequence: licensee references (`ERR_LICENSEE_NOT_FOUND`), then jurisdiction references (`ERR_JURISDICTION_NOT_FOUND`), then control-person references including `parent_control_person_id` (`ERR_CONTROL_PERSON_NOT_FOUND`), then application references (`ERR_APPLICATION_NOT_FOUND`), then state-licence references whether in the path or in a body field (`ERR_LICENSE_NOT_FOUND`), then delegate references (`ERR_DELEGATE_NOT_FOUND`), then delegate-authorization references (`ERR_AUTHORIZATION_NOT_FOUND`), then investment-holding references (`ERR_HOLDING_NOT_FOUND`), then coverage-test references (`ERR_TEST_NOT_FOUND`), then examination references including `exam_id` and `originating_exam_id` (`ERR_EXAM_NOT_FOUND`), then information-request references (`ERR_INFO_REQUEST_NOT_FOUND`), then enforcement-action references (`ERR_ENFORCEMENT_NOT_FOUND`)."
    PRD 2.7: "A request naming a non-existent licensee and a non-existent jurisdiction reports the licensee first."
    PRD 2.3: "The application register filters on `licensee_id`, `jurisdiction_id` and `status`."

    Design: Corner/errors/unknown_foreign_keys_on_write_paths_return_not_found
    """
    response = api.create_application(
        F.application_payload(licensee["id"], NON_EXISTENT_UUID), MANAGER_HEADERS
    )
    validate_error(response, ERR_JURISDICTION_NOT_FOUND)

    rows, meta = validate_paginated(
        api.list_applications(MANAGER_HEADERS, params={"licensee_id": licensee["id"]})
    )
    assert rows == [], f"a rejected filing left an application row behind: {rows}"
    assert meta["total_count"] == 0, "the application register must still be empty"


def test_unknown_holding_id_on_the_dispose_path_returns_holding_not_found(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Disposal addresses an investment holding only by path id, and an absent id reports the holding family's own 404 while the licensee's holdings listing stays empty.

    PRD 2.7: "**Reference resolution**, left to right along the path and then through the body, in this exact sequence: licensee references (`ERR_LICENSEE_NOT_FOUND`), then jurisdiction references (`ERR_JURISDICTION_NOT_FOUND`), then control-person references including `parent_control_person_id` (`ERR_CONTROL_PERSON_NOT_FOUND`), then application references (`ERR_APPLICATION_NOT_FOUND`), then state-licence references whether in the path or in a body field (`ERR_LICENSE_NOT_FOUND`), then delegate references (`ERR_DELEGATE_NOT_FOUND`), then delegate-authorization references (`ERR_AUTHORIZATION_NOT_FOUND`), then investment-holding references (`ERR_HOLDING_NOT_FOUND`), then coverage-test references (`ERR_TEST_NOT_FOUND`), then examination references including `exam_id` and `originating_exam_id` (`ERR_EXAM_NOT_FOUND`), then information-request references (`ERR_INFO_REQUEST_NOT_FOUND`), then enforcement-action references (`ERR_ENFORCEMENT_NOT_FOUND`)."
    PRD 3.7: "The row starts with `status` `HELD`; disposing of it moves it to `DISPOSED`, and only `HELD` rows enter any coverage computation."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/unknown_foreign_keys_on_write_paths_return_not_found
    """
    response = api.dispose_investment_holding(NON_EXISTENT_UUID, OFFICER_HEADERS)
    validate_error(response, ERR_HOLDING_NOT_FOUND)

    rows, meta = validate_paginated(
        api.list_licensee_investment_holdings(licensee["id"], MANAGER_HEADERS)
    )
    assert rows == [], f"a rejected disposal left a holding row behind: {rows}"
    assert meta["total_count"] == 0, "the holdings listing must still be empty"
