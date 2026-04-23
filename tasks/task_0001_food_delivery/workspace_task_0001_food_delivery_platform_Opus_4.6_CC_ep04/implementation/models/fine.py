from models.base import SimpleModel


class Fine(SimpleModel):
    def __init__(self, subject_type, subject_id, reason, amount_cents):
        super().__init__()
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.reason = reason
        self.amount_cents = amount_cents
        self.settlement_status = "PENDING"

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "reason": self.reason,
            "amount_cents": self.amount_cents,
            "settlement_status": self.settlement_status,
        })
        return d
