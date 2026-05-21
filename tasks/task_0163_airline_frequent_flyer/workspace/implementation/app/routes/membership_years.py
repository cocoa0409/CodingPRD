"""Membership year audit listing."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_roles
from ..envelope import ok_array
from ..store import store
from ..services.common import (
    parse_pagination, paginate, get_member_or_404, enforce_member_ownership,
)
from ..services.serialize import serialize_membership_year


membership_years_bp = Blueprint("membership_years", __name__)


@membership_years_bp.get("/members/<member_id>/membership-years")
@require_roles("Member", "ProgramAdmin")
def list_membership_years(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    items = [y for y in store.membership_years.values() if y["member_id"] == member_id]
    items.sort(key=lambda y: y["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_membership_year(y) for y in page]
    return ok_array(data, limit, offset, total, has_more)
