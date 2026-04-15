"""Prerequisite graph computation: transitive closure, cycle detection, topological sort."""
import db


def compute_prerequisite_graph(course_id):
    """Compute the prerequisite graph for a course.
    Returns dict with dependency_chain, depth, has_cycle.
    """
    course = db.courses.get(course_id)
    if not course:
        return None

    # DFS to find transitive closure and detect cycles
    visited = set()
    in_stack = set()
    has_cycle = False
    all_prereqs = []

    def dfs(cid):
        nonlocal has_cycle
        if cid in in_stack:
            has_cycle = True
            return
        if cid in visited:
            return
        in_stack.add(cid)
        visited.add(cid)

        c = db.courses.get(cid)
        if c:
            for prereq_id in (c.get("prerequisite_ids") or []):
                dfs(prereq_id)

        in_stack.remove(cid)
        if cid != course_id:
            all_prereqs.append(cid)

    dfs(course_id)

    # Compute depth (longest path from course to a root)
    depth_cache = {}

    def get_depth(cid, path=None):
        if path is None:
            path = set()
        if cid in path:
            return 0  # cycle, bail
        if cid in depth_cache:
            return depth_cache[cid]

        c = db.courses.get(cid)
        prereqs = (c.get("prerequisite_ids") or []) if c else []
        if not prereqs:
            depth_cache[cid] = 0
            return 0

        path.add(cid)
        max_d = 0
        for pid in prereqs:
            d = get_depth(pid, path) + 1
            if d > max_d:
                max_d = d
        path.discard(cid)
        depth_cache[cid] = max_d
        return max_d

    depth = get_depth(course_id)

    # Topological sort of the transitive prerequisites
    # Reverse post-order gives topological sort
    # all_prereqs is already in reverse-post-order from DFS
    dependency_chain = list(reversed(all_prereqs))

    return {
        "course_id": course_id,
        "dependency_chain": dependency_chain,
        "depth": depth,
        "has_cycle": has_cycle
    }


def check_cycle_on_update(course_id, new_prerequisite_ids):
    """Check if setting prerequisite_ids for course_id would create a cycle.
    Returns True if a cycle would be created.
    """
    # Temporarily set the prereqs and check
    visited = set()
    in_stack = set()

    def dfs(cid):
        if cid in in_stack:
            return True  # cycle
        if cid in visited:
            return False
        in_stack.add(cid)
        visited.add(cid)

        if cid == course_id:
            prereqs = new_prerequisite_ids
        else:
            c = db.courses.get(cid)
            prereqs = (c.get("prerequisite_ids") or []) if c else []

        for pid in prereqs:
            if dfs(pid):
                return True

        in_stack.remove(cid)
        return False

    return dfs(course_id)
