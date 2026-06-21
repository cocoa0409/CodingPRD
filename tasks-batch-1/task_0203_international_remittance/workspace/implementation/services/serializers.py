"""Public serialization. Most entities serialize via common.public; transfers
additionally expose the computed refundable_minor (PRD §3.4, §3.7).
"""
from services.common import public
from services.ledger import compute_refundable


def transfer_view(transfer):
    view = public(transfer)
    view["refundable_minor"] = compute_refundable(transfer)
    return view
