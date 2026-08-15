"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid

from util import wall_now


class Model:
    """Plain record with attribute access."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


customers = {}
aircraft = {}
work_orders = {}
panel_designs = {}
equipment_orders = {}
install_tasks = {}
test_events = {}
regulatory_packages = {}
wb_revisions = {}

_seq = [0]


def next_seq():
    """Global monotone insertion counter; used for stable created_at-ASC ordering."""
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def new_entity(**kw):
    """Create a record with the common system-managed quartet (id, created_at,
    updated_at, version) plus an internal insertion sequence for list sorting."""
    ts = wall_now()
    return Model(
        id=new_id(),
        created_at=ts,
        updated_at=ts,
        version=1,
        _seq=next_seq(),
        **kw,
    )


def touch(ent, bump=True):
    """Refresh updated_at on every mutation; bump version when the change is a
    modification of the resource itself. WorkOrder recomputation of derived
    counters passes bump=False (PRD 2.9: version advances only on status
    transitions, panel-design creation, and overage acknowledgement)."""
    ent.updated_at = wall_now()
    if bump:
        ent.version += 1
