"""Payment row creation and idempotency-key handling."""
import db
from clock import now, iso
from errors import err


def create_payment(*, kind: str, subject_id: str, amount_cents: int,
                   card_id=None, external_ref=None) -> dict:
    """Append a Payment row, enforcing external_ref uniqueness when present."""
    if external_ref is not None and external_ref != "":
        if external_ref in db.external_ref_index:
            raise err("ERR_DUPLICATE_EXTERNAL_REF",
                      "Payment external_ref already used")
    p = {
        "kind": kind,
        "subject_id": subject_id,
        "amount_cents": int(amount_cents),
        "card_id": card_id,
        "processed_at": iso(now()),
        "external_ref": external_ref,
    }
    db.stamp_create(p, common_fields=False)
    db.payments[p["id"]] = p
    if external_ref is not None and external_ref != "":
        db.external_ref_index[external_ref] = p["id"]
    return p
