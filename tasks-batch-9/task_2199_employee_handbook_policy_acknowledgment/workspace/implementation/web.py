"""Shared route helpers."""
import db
import response
import serializers
import validate


def paged(table, rows):
    limit, offset = validate.pagination()
    rows = db.sort_created(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    return response.listing(serializers.dump_list(table, window), limit, offset, total)


def one(table, row, status=200):
    return response.ok(serializers.dump(table, row), status)


def created(table, row):
    return response.ok(serializers.dump(table, row), 201)
