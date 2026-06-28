"""In-memory data store. Starts empty on every boot — NO seeding."""
import uuid


class Store:
    def __init__(self):
        self.members = {}
        self.waivers = {}
        self.memberships = {}
        self.certifications = {}
        self.facilities = {}
        self.routes = {}
        self.check_ins = {}
        self.clinics = {}
        self.enrollments = {}
        self.rentals = {}
        self.incidents = {}


db = Store()


def new_id():
    return str(uuid.uuid4())
