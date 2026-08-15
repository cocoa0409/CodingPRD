from . import (
    accounts,
    ach_rules,
    clock_routes,
    enrollment_users,
    enrollments,
    exceptions,
    fee_entries,
    issue_files,
    liability_cases,
    ops_runs,
    presented_items,
    training_sessions,
)

BLUEPRINTS = [
    enrollments.bp,
    enrollment_users.bp,
    accounts.bp,
    issue_files.bp,
    presented_items.bp,
    exceptions.bp,
    ach_rules.bp,
    liability_cases.bp,
    fee_entries.bp,
    training_sessions.bp,
    ops_runs.bp,
    clock_routes.bp,
]
