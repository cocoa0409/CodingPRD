"""Identifier resolution helpers (PRD section 2.10, ladder positions 4-14)."""

import store


def institution(value):
    return store.lookup(store.institutions, value, "ERR_INSTITUTION_NOT_FOUND")


def giving_period(value):
    return store.lookup(store.giving_periods, value,
                        "ERR_GIVING_PERIOD_NOT_FOUND")


def governance_authorization(value):
    return store.lookup(store.governance_authorizations, value,
                        "ERR_GOVERNANCE_AUTHORIZATION_NOT_FOUND")


def pledge_campaign(value):
    return store.lookup(store.pledge_campaigns, value,
                        "ERR_PLEDGE_CAMPAIGN_NOT_FOUND")


def pledge(value):
    return store.lookup(store.pledges, value, "ERR_PLEDGE_NOT_FOUND")


def collateral_asset(value):
    return store.lookup(store.collateral_assets, value,
                        "ERR_COLLATERAL_ASSET_NOT_FOUND")


def loan_application(value):
    return store.lookup(store.loan_applications, value,
                        "ERR_LOAN_APPLICATION_NOT_FOUND")


def loan(value):
    return store.lookup(store.loans, value, "ERR_LOAN_NOT_FOUND")


def draw_request(value):
    return store.lookup(store.draw_requests, value,
                        "ERR_DRAW_REQUEST_NOT_FOUND")


def covenant(value):
    return store.lookup(store.covenants, value, "ERR_COVENANT_NOT_FOUND")


def workout_plan(value):
    return store.lookup(store.workout_plans, value,
                        "ERR_WORKOUT_PLAN_NOT_FOUND")
