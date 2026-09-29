"""Blueprint registry: every business namespace plus the test-driving clock."""
from routes import (
    agreements,
    audits,
    blackouts,
    clock,
    distributors,
    invoices,
    marketing,
    mfn,
    ratecards,
    renewals,
    reports,
    titles,
    windows,
)

BLUEPRINTS = [
    clock.bp,
    distributors.bp,
    ratecards.bp,
    agreements.bp,
    mfn.bp,
    reports.bp,
    audits.bp,
    titles.bp,
    windows.bp,
    blackouts.bp,
    marketing.bp,
    invoices.bp,
    renewals.bp,
]
