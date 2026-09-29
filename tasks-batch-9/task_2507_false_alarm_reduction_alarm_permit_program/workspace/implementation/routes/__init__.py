"""Domain blueprints, mounted in PRD section 4 order."""

from routes import (admin, allocations, appeals, companies, contacts, dispatch,
                    dockets, fee_schedules, incidents, invoices, payments,
                    permits, reports, sites, suspensions, systems)

BLUEPRINTS = (
    fee_schedules.bp,
    companies.bp,
    sites.bp,
    contacts.bp,
    systems.bp,
    permits.bp,
    dispatch.bp,
    incidents.bp,
    dockets.bp,
    appeals.bp,
    suspensions.bp,
    invoices.bp,
    payments.bp,
    allocations.bp,
    reports.bp,
    admin.bp,
)
