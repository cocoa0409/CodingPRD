"""Pre-built role headers for every role in the PRD.

Four of the five roles carry an opaque operator identifier that the server never
compares to any entity's ``id``, so a shared constant is the canonical form for
them.  ``CorrespondingAuthor`` is different: ``X-User-ID`` is the ``id`` of the
acting ``Author``, and ownership checks compare it to the resource's author
foreign key.  Every ownership-gated call MUST therefore be made with
``make_corresponding_author_headers(author["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identifiers — the shared constant is the canonical form.
    "agreement_admin_headers": build_user_headers("aa-negotiator-01", "AgreementAdmin"),
    "librarian_headers": build_user_headers("librarian-reviewer-07", "ScholCommLibrarian"),
    "fund_manager_headers": build_user_headers("fm-approver-01", "FundManager"),
    "fund_payer_headers": build_user_headers("fm-payer-02", "FundManager"),
    "fund_solo_headers": build_user_headers("fm-solo-09", "FundManager"),
    "fund_other_headers": build_user_headers("fm-other-10", "FundManager"),
    "curator_headers": build_user_headers("curator-queue-03", "RepositoryCurator"),
    # Entity-backed role: this shared constant is only for tests that never pass
    # an ownership check (missing-resource, malformed-payload, wrong-role cases).
    "corresponding_author_headers": build_user_headers(
        "author-unrelated-01", "CorrespondingAuthor"
    ),
}


def make_corresponding_author_headers(author_id: str) -> dict:
    """Headers for a ``CorrespondingAuthor`` acting as the given ``Author``.

    Pass the real ``Author.id`` whenever the call is ownership-gated: recording an
    acceptance, running an eligibility check, creating, resubmitting or
    withdrawing a fund request, creating a deposit, or submitting one.
    """
    return build_user_headers(author_id, "CorrespondingAuthor")


def make_agreement_admin_headers(user_id: str = "aa-negotiator-01") -> dict:
    return build_user_headers(user_id, "AgreementAdmin")


def make_librarian_headers(user_id: str = "librarian-reviewer-07") -> dict:
    return build_user_headers(user_id, "ScholCommLibrarian")


def make_fund_manager_headers(user_id: str = "fm-approver-01") -> dict:
    return build_user_headers(user_id, "FundManager")


def make_curator_headers(user_id: str = "curator-queue-03") -> dict:
    return build_user_headers(user_id, "RepositoryCurator")


ALL_ROLE_NAMES = [
    "AgreementAdmin",
    "ScholCommLibrarian",
    "FundManager",
    "RepositoryCurator",
    "CorrespondingAuthor",
]
