"""Route blueprints, one module per resource group."""

from routes import admin, assessments, claims, coverages, kits, occlusion, plans, referrals, sessions

BLUEPRINTS = (
    admin.bp,
    coverages.bp,
    assessments.bp,
    plans.bp,
    sessions.bp,
    kits.bp,
    claims.bp,
    referrals.bp,
    occlusion.bp,
)
