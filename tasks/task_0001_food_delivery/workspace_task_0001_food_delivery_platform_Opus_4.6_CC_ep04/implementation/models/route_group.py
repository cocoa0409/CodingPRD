from models.base import SimpleModel, format_ts


class RouteGroup(SimpleModel):
    def __init__(self, rider_id, assignment_ids):
        super().__init__()
        self.rider_id = rider_id
        self.assignment_ids = list(assignment_ids)
        self.merged_at = self.created_at
        self.status = "ACTIVE"

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "rider_id": self.rider_id,
            "assignment_ids": self.assignment_ids,
            "merged_at": format_ts(self.merged_at),
            "status": self.status,
        })
        return d
