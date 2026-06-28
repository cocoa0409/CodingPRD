"""Entity serializers — control the exact field set returned per entity.

Most entities carry id/created_at/updated_at/version. ChargerProduct is the one
deliberate exception (PRD §2.4): it carries only id and created_at (no updated_at,
no version).
"""


def _copy(entity):
    return dict(entity)


# For most entities the stored dict already mirrors the wire shape, so a shallow
# copy suffices. Serializers exist so any internal-only fields can be stripped.

def homeowner(e):
    return _copy(e)


def property_(e):
    return _copy(e)


def electrician(e):
    return _copy(e)


def charger_product(e):
    # immutable: id + created_at + business fields only (no updated_at/version)
    return _copy(e)


def install_job(e):
    return _copy(e)


def site_assessment(e):
    return _copy(e)


def quote(e):
    return _copy(e)


def permit_application(e):
    return _copy(e)


def interconnection_request(e):
    return _copy(e)


def dispatch_assignment(e):
    return _copy(e)


def incentive_claim(e):
    return _copy(e)


def panel_upgrade_referral(e):
    return _copy(e)


def warranty_ticket(e):
    return _copy(e)
