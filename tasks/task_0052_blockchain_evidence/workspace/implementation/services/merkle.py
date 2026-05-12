"""Merkle tree over hex-encoded leaves.

For batches we pair siblings; an odd-sized layer duplicates the last node.
Hash function: SHA-256 over the concatenation of the two parent bytes.
"""
import hashlib


def _hash_pair(a_hex: str, b_hex: str) -> str:
    a = bytes.fromhex(a_hex)
    b = bytes.fromhex(b_hex)
    return hashlib.sha256(a + b).hexdigest()


def merkle_root(leaves_hex: list) -> str:
    if not leaves_hex:
        return ""
    layer = list(leaves_hex)
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if (i + 1) < len(layer) else layer[i]
            nxt.append(_hash_pair(left, right))
        layer = nxt
    return layer[0]


def merkle_proof(leaves_hex: list, index: int) -> list:
    """Return a list of {sibling, position} dicts forming an inclusion path."""
    if index < 0 or index >= len(leaves_hex):
        return []
    proof = []
    layer = list(leaves_hex)
    idx = index
    while len(layer) > 1:
        # Pair index
        if idx % 2 == 0:
            sibling_idx = idx + 1 if (idx + 1) < len(layer) else idx
            position = "right"
        else:
            sibling_idx = idx - 1
            position = "left"
        proof.append({"sibling": layer[sibling_idx], "position": position})
        nxt = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if (i + 1) < len(layer) else layer[i]
            nxt.append(_hash_pair(left, right))
        layer = nxt
        idx = idx // 2
    return proof
