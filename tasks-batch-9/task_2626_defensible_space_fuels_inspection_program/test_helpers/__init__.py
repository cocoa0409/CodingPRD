"""Test infrastructure for the Defensible Space Fuels Inspection Program API.

Importing this package gives a test everything it needs: the typed client, the
error vocabulary with its HTTP status map already registered, the PRD's numeric
constants, payload factories, domain assertions and the composite lifecycle
builders.
"""

from .api_client import FireDistrictClient
from .api_errors import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403

from . import assertions, constants, factories, fixtures, types  # noqa: F401
