"""Logical-clock advance + month rollover (PRD §3.12).

Advancing the clock across a calendar-month boundary resets every ATM's
monthly_wd_count to 0 so the interchange tier restarts each month.
"""


def set_clock(store, new_dt):
    old = store.clock.get()
    store.clock.set(new_dt)
    crossed_month = (old.year, old.month) != (new_dt.year, new_dt.month)
    if crossed_month:
        for atm in store.atms.values():
            if atm["monthly_wd_count"] != 0:
                atm["monthly_wd_count"] = 0
                store.touch(atm)
    return new_dt
