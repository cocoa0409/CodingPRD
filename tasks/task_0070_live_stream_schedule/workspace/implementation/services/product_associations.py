"""Product-association create / release helpers."""

import db
from errors import (
    ERR_PRODUCT_CATEGORY_MISMATCH,
    ERR_PRODUCT_CERT_MISSING,
    ERR_PRODUCT_NOT_ON_SHELF,
    ERR_STOCK_INSUFFICIENT,
)


def release_all_for_application(application_id: str) -> None:
    """Move every non-RELEASED, non-REJECTED association of the application
    to RELEASED, restoring product stock counters.
    """
    for assoc in list(db.raw_all("product_associations")):
        if assoc.get("application_id") != application_id:
            continue
        if assoc.get("status") in ("RELEASED", "REJECTED"):
            continue
        qty = int(assoc.get("reserved_quantity", 0))
        pid = assoc.get("product_id")

        def m_assoc(a, qty=qty):
            a["status"] = "RELEASED"
        db.update_entity("product_associations", assoc["id"], m_assoc)

        if pid:
            product = db.raw_get("products", pid)
            if product is not None:
                def m_prod(p, qty=qty):
                    p["reserved_stock"] = max(0, p.get("reserved_stock", 0) - qty)
                    p["available_stock"] = p.get("available_stock", 0) + qty
                db.update_entity("products", pid, m_prod)


def eligibility_error(*, product: dict, streamer: dict,
                      application: dict, reserved_quantity: int):
    """Run the 4-step eligibility ladder. Return (error_spec, reject_reason)
    or (None, None) when the association passes.

    Order (per PRD §3.3): ON_SHELF -> CATEGORY -> CERT -> STOCK.
    Note: stock comparison is against `Product.available_stock` AT THIS
    MOMENT — caller is responsible for pre/post stock arithmetic.
    """
    if product.get("status") != "ON_SHELF":
        return ERR_PRODUCT_NOT_ON_SHELF, "NOT_ON_SHELF"
    declared = application.get("declared_product_categories") or []
    if product.get("category") not in declared:
        return ERR_PRODUCT_CATEGORY_MISMATCH, "CATEGORY_MISMATCH"
    if product.get("requires_professional_cert"):
        cert_cats = streamer.get("professional_cert_categories") or []
        if product.get("category") not in cert_cats:
            return ERR_PRODUCT_CERT_MISSING, "MISSING_CERT"
    if reserved_quantity > product.get("available_stock", 0):
        return ERR_STOCK_INSUFFICIENT, "STOCK_INSUFFICIENT"
    return None, None
