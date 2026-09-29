"""Collection and single-resource reads (PRD section 2.3 filters, section 4)."""
from flask import Blueprint

import enums
from authz import ALL_ROLES
from authz import (
    ROLE_AGENCY_OFFICER,
    ROLE_LENDER,
    ROLE_PROVIDER_ANALYST,
    ROLE_PROVIDER_REVIEWER,
)
from authz import authorize
from db import all_rows
from response import ok, ok_list, paginate
from services import must
from shape import Field, read_page, read_query

bp = Blueprint("reads", __name__)

NON_BORROWER_ROLES = [
    ROLE_PROVIDER_ANALYST,
    ROLE_PROVIDER_REVIEWER,
    ROLE_AGENCY_OFFICER,
    ROLE_LENDER,
]


def _fk(name):
    return Field(name, "string", required=False)


def _enum(name, values):
    return Field(name, "enum", required=False, enum=values)


READS = [
    (
        "communities",
        "/communities",
        [_enum("state_code", enums.STATE_CODES), _enum("participation_status", enums.PARTICIPATION_STATUSES)],
        ALL_ROLES,
    ),
    ("lenders", "/lenders", [], NON_BORROWER_ROLES),
    (
        "map_panels",
        "/map-panels",
        [
            _fk("community_id"),
            _fk("supersedes_panel_id"),
            _fk("map_panel_number"),
            _enum("revision_status", enums.REVISION_STATUSES),
        ],
        ALL_ROLES,
    ),
    (
        "properties",
        "/properties",
        [
            _fk("community_id"),
            _fk("map_panel_number"),
            _enum("geocode_status", enums.GEOCODE_STATUSES),
        ],
        ALL_ROLES,
    ),
    (
        "structures",
        "/structures",
        [
            _fk("property_id"),
            _fk("elevation_source_certificate_id"),
            _enum("occupancy_type", enums.OCCUPANCY_TYPES),
        ],
        ALL_ROLES,
    ),
    (
        "loan_folios",
        "/loan-folios",
        [
            _fk("lender_id"),
            _fk("property_id"),
            _fk("current_determination_id"),
            _enum("compliance_posture", enums.COMPLIANCE_POSTURES),
            _enum("insurance_status", enums.INSURANCE_STATUSES),
        ],
        ALL_ROLES,
    ),
    (
        "determinations",
        "/determinations",
        [
            _fk("loan_folio_id"),
            _fk("structure_id"),
            _fk("map_panel_id"),
            _fk("supersedes_determination_id"),
            _enum("status", enums.DETERMINATION_STATUSES),
            _enum("determination_type", enums.DETERMINATION_TYPES),
        ],
        ALL_ROLES,
    ),
    (
        "disputes",
        "/disputes",
        [
            _fk("determination_id"),
            _fk("revised_determination_id"),
            _enum("status", enums.DISPUTE_STATUSES),
            _enum("basis", enums.DISPUTE_BASES),
        ],
        ALL_ROLES,
    ),
    (
        "elevation_certificates",
        "/elevation-certificates",
        [
            _fk("structure_id"),
            _fk("dispute_id"),
            _fk("reference_panel_id"),
            _enum("status", enums.CERTIFICATE_STATUSES),
        ],
        ALL_ROLES,
    ),
    (
        "map_amendment_requests",
        "/map-amendment-requests",
        [
            _fk("determination_id"),
            _fk("elevation_certificate_id"),
            _enum("status", enums.AMENDMENT_STATUSES),
            _enum("request_type", enums.REQUEST_TYPES),
        ],
        ALL_ROLES,
    ),
    (
        "compliance_notices",
        "/compliance-notices",
        [
            _fk("loan_folio_id"),
            _fk("determination_id"),
            _enum("notice_type", enums.NOTICE_TYPES),
            _enum("status", enums.NOTICE_STATUSES),
        ],
        ALL_ROLES,
    ),
]


def _make_list_view(collection, filters, roles):
    def view():
        authorize(roles)
        values = read_query(filters)
        limit, offset = read_page()
        rows = [
            row
            for row in all_rows(collection)
            if all(row.get(key) == value for key, value in values.items())
        ]
        page, total = paginate(rows, limit, offset)
        return ok_list(page, limit, offset, total)

    return view


def _make_get_view(collection, roles):
    def view(row_id):
        authorize(roles)
        return ok(must(collection, row_id))

    return view


for _collection, _path, _filters, _roles in READS:
    bp.add_url_rule(
        _path,
        endpoint="list_" + _collection,
        view_func=_make_list_view(_collection, _filters, _roles),
        methods=["GET"],
    )
    bp.add_url_rule(
        _path + "/<row_id>",
        endpoint="get_" + _collection,
        view_func=_make_get_view(_collection, _roles),
        methods=["GET"],
    )
