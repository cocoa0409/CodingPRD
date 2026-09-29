"""Route blueprints."""

from routes import compliance, evaluations, reference, referrals, scheduling

BLUEPRINTS = (
    reference.bp,
    referrals.bp,
    evaluations.bp,
    scheduling.bp,
    compliance.bp,
)
