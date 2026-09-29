"""Test infrastructure for the Investor Relations & Shareholder Services API.

Everything a test needs is re-exported here: the framework's validators and
race utilities, the typed client, the domain constants and error ids, the
payload factories, the composite setup fixtures and the domain assertions.

Importing this package also installs the PRD's error-id-to-HTTP-status map into
the framework validators, so ``validate_error`` can check the status of an error
without every test restating it.
"""

from prd_bench_local_runner.testing import (
    GenericApiClient,
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    build_user_headers,
    get_success_data,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import assertions, factories, fixtures
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import (
    AllocationRunSummary,
    ClockState,
    CommonFields,
    Company,
    ConsensusRead,
    Contact,
    Disclosure,
    EntityDict,
    EstimateSubmission,
    InquiryTicket,
    MeetingRequest,
    PayoutLedgerRow,
    ResponseDraft,
    RoadshowEvent,
    TransferAgentInstruction,
)
