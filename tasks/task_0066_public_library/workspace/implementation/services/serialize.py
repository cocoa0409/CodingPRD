"""Serializers — strip internal fields and inject computed/dynamic fields."""
import db


def serialize_book_title(bt: dict) -> dict:
    return db.public(bt)


def serialize_copy(c: dict) -> dict:
    return db.public(c)


def serialize_reader(r: dict) -> dict:
    return db.public(r)


def serialize_card(c: dict) -> dict:
    return db.public(c)


def serialize_loan(l: dict, include_fine_provisional: bool = True) -> dict:
    out = db.public(l)
    if include_fine_provisional:
        from services.common import get_copy, get_book_title
        from services.fines import compute_provisional_fine
        copy = db.copies.get(l["copy_id"])
        if copy:
            bt = db.book_titles.get(copy["book_title_id"])
            if bt and l["status"] in {"BORROWED", "RENEWED", "RECALL_PENDING"}:
                out["fine_accrual_provisional_cents"] = compute_provisional_fine(l, bt)
            else:
                out["fine_accrual_provisional_cents"] = 0
    return out


def serialize_reservation(r: dict) -> dict:
    return db.public(r)


def serialize_fine(f: dict) -> dict:
    return db.public(f)


def serialize_ill_request(i: dict) -> dict:
    return db.public(i)


def serialize_suggestion(s: dict) -> dict:
    return db.public(s)


def serialize_audit_log(a: dict) -> dict:
    out = db.public(a)
    # AuditLog does not carry updated_at or version (PRD §2.4)
    out.pop("updated_at", None)
    out.pop("version", None)
    return out
