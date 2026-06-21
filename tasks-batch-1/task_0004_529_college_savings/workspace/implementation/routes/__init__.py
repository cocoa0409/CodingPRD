"""Route registration entry point."""
from flask import Flask


def register_all(app: Flask) -> None:
    from . import (
        donors,
        beneficiaries,
        accounts,
        scheduled_contributions,
        contributions,
        withdrawals,
        beneficiary_changes,
        state_tax_incentives,
        forms_1099q,
        admin,
    )
    for mod in (
        donors,
        beneficiaries,
        accounts,
        scheduled_contributions,
        contributions,
        withdrawals,
        beneficiary_changes,
        state_tax_incentives,
        forms_1099q,
        admin,
    ):
        mod.register(app)
