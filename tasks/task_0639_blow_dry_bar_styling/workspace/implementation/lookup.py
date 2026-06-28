"""Existence lookups (PRD §2.7). Each returns the entity or raises the
corresponding not-found error."""

import errors
from db import db
from errors import err


def get_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err(errors.ERR_MEMBER_NOT_FOUND, "Member not found")
    return m


def get_chair(chair_id):
    c = db.chairs.get(chair_id)
    if c is None:
        raise err(errors.ERR_CHAIR_NOT_FOUND, "Chair not found")
    return c


def get_stylist(stylist_id):
    s = db.stylists.get(stylist_id)
    if s is None:
        raise err(errors.ERR_STYLIST_NOT_FOUND, "Stylist not found")
    return s


def get_style_service(service_id):
    s = db.style_services.get(service_id)
    if s is None:
        raise err(errors.ERR_STYLE_SERVICE_NOT_FOUND, "Style service not found")
    return s


def get_add_on(add_on_id):
    a = db.add_ons.get(add_on_id)
    if a is None:
        raise err(errors.ERR_ADD_ON_NOT_FOUND, "Add-on not found")
    return a


def get_event_block(block_id):
    b = db.event_blocks.get(block_id)
    if b is None:
        raise err(errors.ERR_EVENT_BLOCK_NOT_FOUND, "Event block not found")
    return b


def get_appointment(appt_id):
    a = db.appointments.get(appt_id)
    if a is None:
        raise err(errors.ERR_APPOINTMENT_NOT_FOUND, "Appointment not found")
    return a


def get_product(product_id):
    p = db.products.get(product_id)
    if p is None:
        raise err(errors.ERR_PRODUCT_NOT_FOUND, "Product not found")
    return p


def get_retail_sale(sale_id):
    s = db.retail_sales.get(sale_id)
    if s is None:
        raise err(errors.ERR_SALE_NOT_FOUND, "Retail sale not found")
    return s


def get_package_purchase(pkg_id):
    p = db.package_purchases.get(pkg_id)
    if p is None:
        raise err(errors.ERR_PACKAGE_NOT_FOUND, "Package purchase not found")
    return p


def get_membership_plan(plan_id):
    # No dedicated not-found error for plan in the catalogue; treated as invalid request.
    return db.membership_plans.get(plan_id)
