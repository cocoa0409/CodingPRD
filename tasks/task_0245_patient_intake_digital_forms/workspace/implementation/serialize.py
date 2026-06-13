"""Output serializers — one per entity (SCAFFOLD §1.1 field sets).

Records are stored internally already in their public field shape, so most
serializers are shallow copies. Internal-only bookkeeping keys (prefixed with
'_') are stripped here.
"""


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def clinic(c):
    return _public(c)


def provider(p):
    return _public(p)


def exam_room(r):
    return _public(r)


def patient(p):
    return _public(p)


def appointment(a):
    return _public(a)


def intake_session(s):
    return _public(s)


def insurance_card(c):
    return _public(c)


def eligibility_check(e):
    return _public(e)


def consent_document(c):
    return _public(c)


def questionnaire_response(q):
    return _public(q)


def copay_payment(p):
    return _public(p)


def queue_entry(q):
    return _public(q)


def room_booking(b):
    return _public(b)


def reminder(r):
    return _public(r)


def demographics_sync_job(j):
    return _public(j)
