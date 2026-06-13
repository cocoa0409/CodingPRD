"""RBAC ownership scoping for read endpoints (PRD §2.1, §3.10).

Publisher: opaque identity, may read everything.
Author: may read a contract + children + statements/lines when contract.author_id == X-User-ID,
        plus its own author record (Author.id == X-User-ID).
Agent:  may read a contract + children + statements/lines when contract.agent_id == X-User-ID,
        plus its own agent record (Agent.id == X-User-ID).

A recognized-but-unowned read is ERR_UNAUTHORIZED (403). Existence (404) is
checked first by callers per priority order.
"""
import errors


def can_read_contract(role, user_id, contract):
    if role == "Publisher":
        return True
    if role == "Author":
        return contract.get("author_id") == user_id
    if role == "Agent":
        return contract.get("agent_id") == user_id
    return False


def assert_read_contract(role, user_id, contract):
    if not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()


def assert_read_author(role, user_id, author):
    # Publisher reads any; Author reads only its own record; Agent cannot.
    if role == "Publisher":
        return
    if role == "Author" and author.get("id") == user_id:
        return
    raise errors.unauthorized()


def assert_read_agent(role, user_id, agent):
    if role == "Publisher":
        return
    if role == "Agent" and agent.get("id") == user_id:
        return
    raise errors.unauthorized()
