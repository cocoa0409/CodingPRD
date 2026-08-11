"""Shared route plumbing: envelopes, listing, filtering."""

import envelope
import gates
import serial
import store


def one(collection, record, status=200):
    return envelope.object_response(serial.dump(collection, record), status)


def raw(data, status=200):
    return envelope.object_response(data, status)


def listing(collection, req, rows):
    limit, offset = gates.parse_pagination(req.args)
    total = len(rows)
    window = rows[offset:offset + limit]
    return envelope.array_response([serial.dump(collection, r) for r in window],
                                   limit, offset, total)


def filtered(rows, args, fields):
    """Filters combine conjunctively; a filter matches on the stored field value."""
    out = rows
    for field in fields:
        if field in args:
            wanted = args.get(field)
            out = [r for r in out if r.get(field) is not None and str(r.get(field)) == wanted]
    return out
