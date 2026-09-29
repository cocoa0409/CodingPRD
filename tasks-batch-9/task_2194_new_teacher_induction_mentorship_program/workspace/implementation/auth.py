"""Authentication, role authorization, identity resolution and ownership."""

import functools

from flask import g, request

from errors import ApiError
from store import db

ROLES = (
    "ProgramAdmin",
    "SiteInductionLead",
    "Mentor",
    "NoviceTeacher",
    "StateCredentialingOfficer",
)

# entity-backed identities: role -> collection holding the identity row
ENTITY_BACKED = {
    "SiteInductionLead": "sites",
    "Mentor": "mentors",
    "NoviceTeacher": "novices",
}

ADMIN = "ProgramAdmin"
LEAD = "SiteInductionLead"
MENTOR = "Mentor"
NOVICE = "NoviceTeacher"
STATE = "StateCredentialingOfficer"


def guard(roles):
    """Ladder rungs 1-4: role present, role known, role authorized, identity."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            # 1 - role header present and non-empty
            if role is None or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            role = role.strip()
            # 2 - role recognised
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ENTITY_BACKED and (user_id is None or not str(user_id).strip()):
                raise ApiError("ERR_UNAUTHENTICATED")
            # 3 - role authorized for this operation
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            # 4 - identity resolves for entity-backed roles
            identity = None
            if role in ENTITY_BACKED:
                if user_id is None or not str(user_id).strip():
                    raise ApiError("ERR_IDENTITY_NOT_RESOLVED")
                identity = getattr(db, ENTITY_BACKED[role]).get(str(user_id).strip())
                if identity is None:
                    raise ApiError("ERR_IDENTITY_NOT_RESOLVED")
            g.role = role
            g.user_id = str(user_id).strip() if user_id is not None else None
            g.identity = identity
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def role():
    return getattr(g, "role", None)


def actor():
    return getattr(g, "user_id", None)


# ---------------------------------------------------------------- ownership

def deny_ownership():
    raise ApiError("ERR_OWNERSHIP_VIOLATION")


def own_site(site_id):
    """SiteInductionLead may only touch rows anchored on its own site."""
    if role() == LEAD and site_id != actor():
        deny_ownership()


def own_mentor(mentor_id):
    if role() == MENTOR and mentor_id != actor():
        deny_ownership()


def own_novice_row(novice):
    """Ownership for a resource that reaches a novice."""
    if novice is None:
        return
    r = role()
    if r == LEAD:
        own_site(novice.get("site_id"))
    elif r == NOVICE and novice.get("id") != actor():
        deny_ownership()
    elif r == MENTOR:
        for m in db.matches.values():
            if m.get("novice_id") == novice.get("id") and m.get("mentor_id") == actor():
                return
        deny_ownership()


def own_match(match):
    if match is None:
        return
    r = role()
    if r == MENTOR:
        own_mentor(match.get("mentor_id"))
    elif r == NOVICE:
        if match.get("novice_id") != actor():
            deny_ownership()
    elif r == LEAD:
        novice = db.novices.get(match.get("novice_id"))
        if novice is not None:
            own_site(novice.get("site_id"))


def match_of(row):
    return db.matches.get(row.get("match_id"))


def novice_of_match(match):
    if match is None:
        return None
    return db.novices.get(match.get("novice_id"))


def own_via_match(row):
    """Ownership for contact logs and observation cycles."""
    own_match(match_of(row))


def scope_rows(rows, novice_getter=None, match_getter=None, site_getter=None,
               mentor_getter=None, novice_id_getter=None):
    """Confine list reads to the rows the acting identity may see."""
    r = role()
    if r in (ADMIN, STATE):
        return rows
    out = []
    for row in rows:
        if r == LEAD:
            site_id = None
            if site_getter is not None:
                site_id = site_getter(row)
            elif novice_getter is not None:
                nov = novice_getter(row)
                site_id = nov.get("site_id") if nov else None
            elif match_getter is not None:
                m = match_getter(row)
                nov = novice_of_match(m)
                site_id = nov.get("site_id") if nov else None
            else:
                out.append(row)
                continue
            if site_id == actor():
                out.append(row)
        elif r == MENTOR:
            mentor_id = None
            if mentor_getter is not None:
                mentor_id = mentor_getter(row)
            elif match_getter is not None:
                m = match_getter(row)
                mentor_id = m.get("mentor_id") if m else None
            else:
                out.append(row)
                continue
            if mentor_id == actor():
                out.append(row)
        elif r == NOVICE:
            nid = None
            if novice_id_getter is not None:
                nid = novice_id_getter(row)
            elif novice_getter is not None:
                nov = novice_getter(row)
                nid = nov.get("id") if nov else None
            elif match_getter is not None:
                m = match_getter(row)
                nid = m.get("novice_id") if m else None
            else:
                out.append(row)
                continue
            if nid == actor():
                out.append(row)
        else:
            out.append(row)
    return out
