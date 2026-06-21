from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.courses = {}
        self.golfers = {}
        self.scores = {}
        self.tee_times = {}
        self.bookings = {}
        self.revisions = {}
        self.revision_counter = 0
        self.seq_counter = 0
        # logical clock used by ERR_SLOT_START_PASSED checks; defaults to real now
        self.current_utc = datetime.now(timezone.utc)

    def next_seq(self):
        self.seq_counter += 1
        return self.seq_counter


db = DB()
