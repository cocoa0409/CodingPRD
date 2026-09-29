"""Shared pytest configuration for the precision optics manufacturing suite.

The harness restarts the server before every individual test, so each test
starts against an empty database and builds every precondition it needs through
the API itself. Importing the helper package registers the error-identifier to
HTTP-status map with the framework.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_helpers  # noqa: F401,E402
from test_helpers.fixtures import (  # noqa: F401,E402
    admin_headers,
    aligned_assembly_context,
    api,
    certified_lot,
    coated_context,
    export_decider_headers,
    export_headers,
    figure_accepted_context,
    metrology_headers,
    metrology_signer_headers,
    optics_engineer_headers,
    procurement_headers,
    quality_headers,
    quality_second_headers,
    releasable_assembly_context,
    released_design,
    released_to_assembly_context,
    sealed_assembly_context,
    technician_headers,
    work_order_context,
)
