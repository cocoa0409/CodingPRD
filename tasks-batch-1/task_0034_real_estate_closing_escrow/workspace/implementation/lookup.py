"""Existence resolution helpers (PRD §2.8 — left-to-right path resolution)."""
from __future__ import annotations

from db import DB_INSTANCE
from errors import ERR_FK_NOT_FOUND, ERR_NOT_FOUND, err


def get_agreement_or_404(agreement_id: str) -> dict:
    a = DB_INSTANCE.purchase_agreements.get(agreement_id)
    if a is None:
        raise err(ERR_NOT_FOUND, f"PurchaseAgreement {agreement_id} not found")
    return a


def get_escrow_or_404(escrow_id: str) -> dict:
    e = DB_INSTANCE.escrow_accounts.get(escrow_id)
    if e is None:
        raise err(ERR_NOT_FOUND, f"EscrowAccount {escrow_id} not found")
    return e


def get_deposit_or_404(deposit_id: str) -> dict:
    d = DB_INSTANCE.earnest_money_deposits.get(deposit_id)
    if d is None:
        raise err(ERR_NOT_FOUND, f"EarnestMoneyDeposit {deposit_id} not found")
    return d


def get_title_search_or_404(ts_id: str) -> dict:
    t = DB_INSTANCE.title_searches.get(ts_id)
    if t is None:
        raise err(ERR_NOT_FOUND, f"TitleSearch {ts_id} not found")
    return t


def get_title_policy_or_404(p_id: str) -> dict:
    p = DB_INSTANCE.title_insurance_policies.get(p_id)
    if p is None:
        raise err(ERR_NOT_FOUND, f"TitleInsurancePolicy {p_id} not found")
    return p


def get_ccr_or_404(c_id: str) -> dict:
    c = DB_INSTANCE.ccr_reviews.get(c_id)
    if c is None:
        raise err(ERR_NOT_FOUND, f"CCRReview {c_id} not found")
    return c


def get_cd_or_404(cd_id: str) -> dict:
    cd = DB_INSTANCE.closing_disclosures.get(cd_id)
    if cd is None:
        raise err(ERR_NOT_FOUND, f"ClosingDisclosure {cd_id} not found")
    return cd


def get_wire_or_404(w_id: str) -> dict:
    w = DB_INSTANCE.wire_instructions.get(w_id)
    if w is None:
        raise err(ERR_NOT_FOUND, f"WireInstruction {w_id} not found")
    return w


def get_disbursement_or_404(d_id: str) -> dict:
    d = DB_INSTANCE.disbursements.get(d_id)
    if d is None:
        raise err(ERR_NOT_FOUND, f"Disbursement {d_id} not found")
    return d


def get_exchange_or_404(x_id: str) -> dict:
    x = DB_INSTANCE.exchange_accounts.get(x_id)
    if x is None:
        raise err(ERR_NOT_FOUND, f"ExchangeAccount {x_id} not found")
    return x


def get_user_or_404(u_id: str) -> dict:
    u = DB_INSTANCE.users.get(u_id)
    if u is None:
        raise err(ERR_NOT_FOUND, f"User {u_id} not found")
    return u


def get_fk_agreement(agreement_id: str) -> dict:
    a = DB_INSTANCE.purchase_agreements.get(agreement_id)
    if a is None:
        raise err(ERR_FK_NOT_FOUND, f"PurchaseAgreement {agreement_id} not found")
    return a


def get_fk_escrow(escrow_id: str) -> dict:
    e = DB_INSTANCE.escrow_accounts.get(escrow_id)
    if e is None:
        raise err(ERR_FK_NOT_FOUND, f"EscrowAccount {escrow_id} not found")
    return e


def get_fk_title_search(ts_id: str) -> dict:
    t = DB_INSTANCE.title_searches.get(ts_id)
    if t is None:
        raise err(ERR_FK_NOT_FOUND, f"TitleSearch {ts_id} not found")
    return t


def get_fk_wire(w_id: str) -> dict:
    w = DB_INSTANCE.wire_instructions.get(w_id)
    if w is None:
        raise err(ERR_FK_NOT_FOUND, f"WireInstruction {w_id} not found")
    return w


def get_fk_exchange(x_id: str) -> dict:
    x = DB_INSTANCE.exchange_accounts.get(x_id)
    if x is None:
        raise err(ERR_FK_NOT_FOUND, f"ExchangeAccount {x_id} not found")
    return x
