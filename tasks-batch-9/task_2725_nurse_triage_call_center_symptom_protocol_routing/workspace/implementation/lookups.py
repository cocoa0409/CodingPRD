"""Existence checks — validation priorities 4 through 13. Each helper raises the
error the priority table assigns to its entity, and callers invoke them in
ascending priority order so that a request naming two missing rows reports the
lower-numbered one.
"""
from errors import ApiError
from store import store


def practice(practice_id):
    row = store.practices.get(practice_id)
    if row is None:
        raise ApiError("ERR_PRACTICE_NOT_FOUND")
    return row


def nurse(nurse_id):
    row = store.nurses.get(nurse_id)
    if row is None:
        raise ApiError("ERR_NURSE_NOT_FOUND")
    return row


def patient(patient_id):
    row = store.patients.get(patient_id)
    if row is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    return row


def protocol(protocol_id):
    row = store.protocols.get(protocol_id)
    if row is None:
        raise ApiError("ERR_PROTOCOL_NOT_FOUND")
    return row


def call(call_id):
    row = store.calls.get(call_id)
    if row is None:
        raise ApiError("ERR_TRIAGE_CALL_NOT_FOUND")
    return row


def assessment(assessment_id):
    row = store.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND")
    return row


def disposition(disposition_id):
    row = store.dispositions.get(disposition_id)
    if row is None:
        raise ApiError("ERR_DISPOSITION_NOT_FOUND")
    return row


def callback_task(task_id):
    row = store.callback_tasks.get(task_id)
    if row is None:
        raise ApiError("ERR_CALLBACK_TASK_NOT_FOUND")
    return row


def warm_transfer(transfer_id):
    row = store.warm_transfers.get(transfer_id)
    if row is None:
        raise ApiError("ERR_WARM_TRANSFER_NOT_FOUND")
    return row


def coverage_window(window_id):
    row = store.coverage_windows.get(window_id)
    if row is None:
        raise ApiError("ERR_COVERAGE_WINDOW_NOT_FOUND")
    return row
