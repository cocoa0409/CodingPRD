"""Route blueprint registration."""

from . import staff, prospects, proposals, pledges, payments, funds, campaigns

ALL_BLUEPRINTS = [
    staff.bp,
    prospects.bp,
    proposals.bp,
    pledges.bp,
    payments.bp,
    funds.bp,
    campaigns.bp,
]
