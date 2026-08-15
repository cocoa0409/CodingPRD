from flask import Blueprint

from routes import (
    audit,
    authorities,
    clock,
    employees,
    employers,
    lists,
    orders,
    payroll_runs,
    remittances,
    state_rules,
)


def register_all(app):
    for module in (
        clock,
        employers,
        state_rules,
        authorities,
        employees,
        orders,
        payroll_runs,
        remittances,
        audit,
        lists,
    ):
        app.register_blueprint(module.bp)
