"""Composite setup helpers for the eDiscovery & Litigation Hold workflows.

These encapsulate the multi-step preambles that most interesting claims require:
opening a matter, registering custodians, issuing/acknowledging a hold, defining
and running collection, dedup processing, review batches and decisions, Bates
production sets, and clawbacks.

All setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup step failed" error rather than a confusing assertion later.

Identity threading: the Custodian role is entity-backed, so any acknowledge call
uses make_custodian_headers(custodian["id"]) — never the shared fallback header.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_custodian_headers,
)
from . import factories as F

LEGALOPS = TEST_USERS["legalops_headers"]
REVIEWLEAD = TEST_USERS["reviewlead_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
PRODUCER = TEST_USERS["producer_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Pin the server clock for deterministic now-stamping (PRD §3.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, LEGALOPS))


# ---------------------------------------------------------------------------
# Tier 1: matter / custodian / hold primitives
# ---------------------------------------------------------------------------
def create_matter(caption="Acme v. Beta", bates_prefix="ABC", **overrides) -> dict:
    payload = F.create_matter_payload(caption=caption, bates_prefix=bates_prefix, **overrides)
    return get_success_data(api_client.create_matter(payload, LEGALOPS))


def create_custodian(matter_id, full_name="Alice", email="alice@x.com", **overrides) -> dict:
    payload = F.create_custodian_payload(
        matter_id, full_name=full_name, email=email, **overrides
    )
    return get_success_data(api_client.create_custodian(payload, LEGALOPS))


def create_hold(matter_id, ack_deadline="2026-06-10T00:00:00Z", **overrides) -> dict:
    payload = F.create_legal_hold_payload(matter_id, ack_deadline=ack_deadline, **overrides)
    return get_success_data(api_client.create_legal_hold(payload, LEGALOPS))


def issue_hold(hold_id) -> dict:
    return get_success_data(api_client.issue_legal_hold(hold_id, LEGALOPS))


def acknowledgement_id_for(custodian_id) -> str:
    data, _meta = _list(api_client.list_hold_acknowledgements(
        LEGALOPS, params={"custodian_id": custodian_id}
    ))
    assert data, f"No acknowledgement found for custodian {custodian_id}"
    return data[0]["id"]


def acknowledge(ack_id, custodian_id) -> dict:
    """Acknowledge a hold notice as the owning custodian (entity-backed identity)."""
    return get_success_data(
        api_client.acknowledge(ack_id, make_custodian_headers(custodian_id))
    )


def _list(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def setup_matter_with_acknowledged_custodian(
    caption="Acme v. Beta", bates_prefix="ABC",
    full_name="Alice", email="alice@x.com",
    ack_deadline="2026-06-10T00:00:00Z",
):
    """Matter with HOLD_ACTIVE and one ACKNOWLEDGED custodian.

    Returns dict(matter, custodian, hold). The matter's hold_status is
    HOLD_ACTIVE (issue bubbled it) and the custodian.ack_state==ACKNOWLEDGED.
    """
    matter = create_matter(caption=caption, bates_prefix=bates_prefix)
    custodian = create_custodian(matter["id"], full_name=full_name, email=email)
    hold = create_hold(matter["id"], ack_deadline=ack_deadline)
    issue_hold(hold["id"])
    ack_id = acknowledgement_id_for(custodian["id"])
    acknowledge(ack_id, custodian["id"])
    return {"matter": matter, "custodian": custodian, "hold": hold, "ack_id": ack_id}


# ---------------------------------------------------------------------------
# Tier 2: collection scope + documents
# ---------------------------------------------------------------------------
def create_scope(
    matter_id, custodian_id,
    source_label="Mbx",
    range_start="2026-06-01T00:00:00Z",
    range_end="2026-06-30T00:00:00Z",
    expected_doc_count=1,
    **overrides,
) -> dict:
    payload = F.create_collection_scope_payload(
        matter_id, custodian_id,
        source_label=source_label, range_start=range_start,
        range_end=range_end, expected_doc_count=expected_doc_count, **overrides,
    )
    return get_success_data(api_client.create_collection_scope(payload, LEGALOPS))


def start_scope(scope_id):
    return get_success_data(api_client.start_collection_scope(scope_id, LEGALOPS))


def finish_scope(scope_id):
    return get_success_data(api_client.finish_collection_scope(scope_id, LEGALOPS))


def _as_hex(label) -> str:
    """Map a content-hash label to a valid hexadecimal string.

    PRD §3.4 requires the ingested ``content_hash`` to be a non-empty hexadecimal
    string. Tests pass short human-readable labels ("A", "DUP", "h1", ...) whose
    only meaningful property is equality/distinctness (dedup is keyed on hash
    equality). This encodes each label's UTF-8 bytes to hex deterministically, so
    identical labels yield identical hex (same dedup bucket) and distinct labels
    yield distinct hex (different bucket), while every value is valid hexadecimal.
    """
    return label.encode("utf-8").hex()


def ingest_document(scope_id, content_hash, page_count=1) -> dict:
    payload = F.create_document_payload(
        scope_id, content_hash=_as_hex(content_hash), page_count=page_count
    )
    return get_success_data(api_client.create_document(payload, LEGALOPS))


def setup_collecting_scope(matter_id, custodian_id, expected_doc_count=1, **scope_overrides):
    """Create a scope and start it (status COLLECTING). Returns the scope dict."""
    scope = create_scope(
        matter_id, custodian_id, expected_doc_count=expected_doc_count, **scope_overrides
    )
    start_scope(scope["id"])
    return scope


def setup_collected_scope_with_docs(
    matter_id, custodian_id, content_hashes, page_counts=None,
    expected_doc_count=None, **scope_overrides,
):
    """Create + start a scope, ingest one doc per hash, finish collection.

    Returns (scope, [documents]). Documents are still status COLLECTED.
    """
    if page_counts is None:
        page_counts = [1] * len(content_hashes)
    if expected_doc_count is None:
        expected_doc_count = len(content_hashes)
    scope = setup_collecting_scope(
        matter_id, custodian_id, expected_doc_count=expected_doc_count, **scope_overrides
    )
    docs = [
        ingest_document(scope["id"], h, pc)
        for h, pc in zip(content_hashes, page_counts)
    ]
    finish_scope(scope["id"])
    return scope, docs


# ---------------------------------------------------------------------------
# Tier 3: processing / dedup
# ---------------------------------------------------------------------------
def create_job(matter_id, scope_id) -> dict:
    payload = F.create_processing_job_payload(matter_id, scope_id)
    return get_success_data(api_client.create_processing_job(payload, LEGALOPS))


def run_job(job_id):
    return get_success_data(api_client.run_processing_job(job_id, LEGALOPS))


def complete_job(job_id) -> dict:
    return get_success_data(api_client.complete_processing_job(job_id, LEGALOPS))


def process_scope(matter_id, scope_id):
    """Queue, run, and complete a processing job for a COLLECTED scope.

    Returns the completed ProcessingJob dict (carries unique/duplicate counts).
    Also bubbles scope->PROCESSED and (first job) matter->IN_DISCOVERY.
    """
    job = create_job(matter_id, scope_id)
    run_job(job["id"])
    return complete_job(job["id"])


def setup_processed_scope(
    matter_id, custodian_id, content_hashes, page_counts=None,
    expected_doc_count=None, **scope_overrides,
):
    """Collect + ingest + process a scope. Returns (scope, [documents], job).

    After this the documents have been partitioned into UNIQUE/DUPLICATE and the
    matter lifecycle is IN_DISCOVERY (if this was the first completed job).
    """
    scope, docs = setup_collected_scope_with_docs(
        matter_id, custodian_id, content_hashes, page_counts=page_counts,
        expected_doc_count=expected_doc_count, **scope_overrides,
    )
    job = process_scope(matter_id, scope["id"])
    # Refresh documents to pick up dedup status/duplicate_of_id.
    refreshed = [
        get_success_data(api_client.get_document(d["id"], LEGALOPS)) for d in docs
    ]
    return scope, refreshed, job


# ---------------------------------------------------------------------------
# Tier 4: review batch + decisions + tag freeze
# ---------------------------------------------------------------------------
def create_batch(matter_id, name="B1") -> dict:
    payload = F.create_review_batch_payload(matter_id, name=name)
    return get_success_data(api_client.create_review_batch(payload, REVIEWLEAD))


def add_review(batch_id, document_id) -> dict:
    payload = F.add_review_payload(document_id)
    return get_success_data(api_client.add_review(batch_id, payload, REVIEWLEAD))


def open_review(batch_id):
    return get_success_data(api_client.open_review(batch_id, REVIEWLEAD))


def decide(review_id, decision, reviewer_user_id=None) -> dict:
    payload = F.decide_review_payload(decision)
    headers = (
        TEST_USERS["reviewer_headers"]
        if reviewer_user_id is None
        else {"X-User-ID": reviewer_user_id, "X-User-Role": "Reviewer",
              "Content-Type": "application/json"}
    )
    return get_success_data(api_client.decide_review(review_id, payload, headers))


def submit_qc(batch_id):
    return get_success_data(api_client.submit_qc(batch_id, REVIEWLEAD))


def reopen(batch_id):
    return get_success_data(api_client.reopen_review(batch_id, REVIEWLEAD))


def complete_batch(batch_id) -> dict:
    return get_success_data(api_client.complete_review_batch(batch_id, REVIEWLEAD))


def setup_completed_batch(
    matter_id, documents, decisions, name="B1", reviewer_user_id=None,
):
    """Build a batch over the given UNIQUE documents, decide each per `decisions`,
    drive through submit-qc and complete (tags frozen).

    `documents` and `decisions` are positionally paired. Returns
    (batch, [review_rows]). On complete, each document's tags are frozen from
    its decision per the §3.6 mapping.
    """
    batch = create_batch(matter_id, name=name)
    reviews = [add_review(batch["id"], d["id"]) for d in documents]
    open_review(batch["id"])
    for review, decision in zip(reviews, decisions):
        decide(review["id"], decision, reviewer_user_id=reviewer_user_id)
    submit_qc(batch["id"])
    complete_batch(batch["id"])
    return batch, reviews


# ---------------------------------------------------------------------------
# Tier 5: production set lifecycle + clawback
# ---------------------------------------------------------------------------
def create_production_set(matter_id, source_batch_id) -> dict:
    payload = F.create_production_set_payload(matter_id, source_batch_id)
    return get_success_data(api_client.create_production_set(payload, PRODUCER))


def add_item(set_id, document_id) -> dict:
    payload = F.add_production_item_payload(document_id)
    return get_success_data(api_client.add_production_item(set_id, payload, PRODUCER))


def validate_set(set_id) -> dict:
    return get_success_data(api_client.validate_production_set(set_id, PRODUCER))


def produce_set(set_id, producer_user_id=None) -> dict:
    headers = (
        PRODUCER
        if producer_user_id is None
        else {"X-User-ID": producer_user_id, "X-User-Role": "Producer",
              "Content-Type": "application/json"}
    )
    return get_success_data(api_client.produce_production_set(set_id, headers))


def list_items_on_set(set_id):
    data, _meta = _list(api_client.list_production_items_on_set(set_id, PRODUCER))
    return data


def setup_staged_set(matter_id, source_batch_id, document_ids):
    """Create a production set, add the given documents as items, validate it
    to STAGED (Bates allocated). Returns the validated ProductionSet dict.
    """
    ps = create_production_set(matter_id, source_batch_id)
    for doc_id in document_ids:
        add_item(ps["id"], doc_id)
    return validate_set(ps["id"])


def setup_produced_set(matter_id, source_batch_id, document_ids, producer_user_id=None):
    """Full path through PRODUCED. Returns (production_set, [items]).

    The set is validated to STAGED and produced; items move to PRODUCED.
    """
    ps = create_production_set(matter_id, source_batch_id)
    for doc_id in document_ids:
        add_item(ps["id"], doc_id)
    validate_set(ps["id"])
    produced = produce_set(ps["id"], producer_user_id=producer_user_id)
    items = list_items_on_set(ps["id"])
    return produced, items


def file_clawback(matter_id, production_item_id, expected_version, reason="review") -> dict:
    payload = F.create_clawback_payload(
        matter_id, production_item_id, expected_version, reason=reason
    )
    return get_success_data(api_client.create_clawback(payload, PRODUCER))


def sequester(clawback_id) -> dict:
    return get_success_data(api_client.sequester_clawback(clawback_id, PRODUCER))


# ---------------------------------------------------------------------------
# Composite end-to-end shortcuts used by several difficulty instances
# ---------------------------------------------------------------------------
def setup_produced_set_from_responsive_docs(
    caption="Prod Co", bates_prefix="PC", num_docs=2, page_counts=None,
    reviewer_user_id=None, producer_user_id=None,
):
    """Full lifecycle: matter -> acknowledged custodian -> collect N unique docs
    -> process -> review all RESPONSIVE_NOT_PRIV -> complete batch -> production
    set -> validate STAGED -> produce.

    Returns dict(matter, custodian, hold, scope, documents, job, batch, reviews,
    production_set, items).
    """
    if page_counts is None:
        page_counts = [1] * num_docs
    base = setup_matter_with_acknowledged_custodian(
        caption=caption, bates_prefix=bates_prefix
    )
    m_id = base["matter"]["id"]
    hashes = [f"h{i}" for i in range(num_docs)]
    scope, docs, job = setup_processed_scope(
        m_id, base["custodian"]["id"], hashes, page_counts=page_counts,
        expected_doc_count=num_docs,
    )
    decisions = ["RESPONSIVE_NOT_PRIV"] * num_docs
    batch, reviews = setup_completed_batch(
        m_id, docs, decisions, reviewer_user_id=reviewer_user_id
    )
    produced, items = setup_produced_set(
        m_id, batch["id"], [d["id"] for d in docs], producer_user_id=producer_user_id
    )
    return {
        "matter": base["matter"], "custodian": base["custodian"], "hold": base["hold"],
        "scope": scope, "documents": docs, "job": job, "batch": batch,
        "reviews": reviews, "production_set": produced, "items": items,
    }
