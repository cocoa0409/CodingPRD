"""Public serialization of stored records. We store records as dicts that already
hold the public shape, so serialization is mostly a shallow copy. Kept as a layer
so field selection stays explicit and consistent."""


def _copy(record):
    return dict(record)


def customer(r):
    return _copy(r)


def catalog_product(r):
    return _copy(r)


def component(r):
    return _copy(r)


def rush_policy(r):
    return _copy(r)


def promo_code(r):
    return _copy(r)


def order(r):
    return _copy(r)


def order_line(r):
    return _copy(r)


def proof(r):
    return _copy(r)


def component_allocation(r):
    return _copy(r)


def payment(r):
    return _copy(r)


def fulfillment(r):
    return _copy(r)
