"""Public serializers — strip internal keys. Records already hold exactly the
fields each entity exposes, so serialization is just a clean copy."""
import db


def out(rec):
    return db.public(rec)


def out_list(recs):
    return [db.public(r) for r in recs]
