from models.base import VersionedModel


class WorkOrder(VersionedModel):
    def __init__(self, opened_by_role, opened_by_id, category,
                 related_order_id=None, related_return_id=None):
        super().__init__()
        self.opened_by_role = opened_by_role
        self.opened_by_id = opened_by_id
        self.category = category
        self.related_order_id = related_order_id
        self.related_return_id = related_return_id
        self.resolution_notes = None
        self.assigned_cs_user_id = None
        self.status = "OPEN"

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "opened_by_role": self.opened_by_role,
            "opened_by_id": self.opened_by_id,
            "category": self.category,
            "related_order_id": self.related_order_id,
            "related_return_id": self.related_return_id,
            "resolution_notes": self.resolution_notes,
            "assigned_cs_user_id": self.assigned_cs_user_id,
            "status": self.status,
        })
        return d
