"""Vehicle state-machine side effects and availability reconciliation.

available_count / total_count on a VehicleClass are denormalized caches that are
recomputed from Vehicle rows on every status change (PRD §2.5). We never store
the counts on the class record; serialize.vehicle_class derives them live. The
reconcile here therefore only needs to bump the affected class's updated_at /
version so its mutation is observable (cascade rule, PRD §2.5).
"""
import util


def reconcile_class(vclass):
    """Cascade: the class's denormalized counts changed → bump its version/updated_at."""
    util.touch(vclass)
