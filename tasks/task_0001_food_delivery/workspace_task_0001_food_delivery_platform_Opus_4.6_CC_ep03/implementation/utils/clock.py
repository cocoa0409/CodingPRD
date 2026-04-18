from datetime import datetime, timezone, timedelta


class LogicalClock:
    def __init__(self):
        self._offset = timedelta(0)

    def now(self):
        return datetime.now(timezone.utc) + self._offset

    def advance(self, seconds):
        self._offset += timedelta(seconds=seconds)

    def format(self, dt):
        return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


clock = LogicalClock()
