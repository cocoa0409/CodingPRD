"""
Shared test infrastructure for the Wrestling Weight Certification API.

Modules:

* ``constants``   — role names, season constant defaults, every enumeration
                    member and the worked figures the requirements compute.
* ``types``       — response shapes, including the split between mutable rows
                    and the three append-only rows.
* ``api_client``  — one method per declared endpoint.
* ``api_errors``  — every error identifier and its paired HTTP status.
* ``factories``   — request-body builders with correct JSON types.
* ``assertions``  — half-up rounding, derived-figure arithmetic, row shapes and
                    the two conserved aggregates.
* ``test_users``  — identity headers for the five roles.
* ``fixtures``    — the ``api`` fixture and the composite setup chains.
"""

from . import constants  # noqa: F401
from . import types  # noqa: F401
from . import api_client  # noqa: F401
from . import factories  # noqa: F401
from . import assertions  # noqa: F401
from . import test_users  # noqa: F401
from . import fixtures  # noqa: F401

# Imported last, and for its side effect: it registers the error-to-status
# mapping with the framework validator.
from . import api_errors  # noqa: F401
