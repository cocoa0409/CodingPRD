from models.base import VersionedModel


class Return(VersionedModel):
    def __init__(self, order_id, reason, requested_refund_cents):
        super().__init__()
        self.order_id = order_id
        self.reason = reason
        self.requested_refund_cents = requested_refund_cents
        self.approved_refund_cents = None
        self.reviewer_cs_user_id = None
        self.status = "REQUESTED"

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "order_id": self.order_id,
            "reason": self.reason,
            "requested_refund_cents": self.requested_refund_cents,
            "approved_refund_cents": self.approved_refund_cents,
            "reviewer_cs_user_id": self.reviewer_cs_user_id,
            "status": self.status,
        })
        return d
