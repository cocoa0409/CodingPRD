import json, glob, sys, collections
TD = "/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing"
files = sorted(glob.glob(TD + "/workspace/implementation/results.*.json"))
if len(files) != 8:
    print("INCOMPLETE %d" % len(files)); sys.exit(3)
env_marks = ("lsof", "Connection aborted", "ConnectionResetError",
             "Max retries", "Failed to establish", "Server did not become ready",
             "RemoteDisconnected", "Connection refused")
clean = True
real = []
cat = collections.Counter()
for f in files:
    d = json.load(open(f))
    if d["passed"] != d["total"]:
        clean = False
    for t in d["tests"]:
        if t["status"] != "passed":
            m = t.get("error_message") or ""
            if any(k in m for k in env_marks):
                cat["env"] += 1
            else:
                cat["real"] += 1
                real.append((f[-7:-5], t["file"].split("/")[-1], t["name"], m))
    print("%s %d/%d f=%d e=%d" % (f.split("/")[-1], d["passed"], d["total"], d["failed"], d["errors"]))
print("counts", dict(cat))
for r in real:
    print("=== round %s %s::%s" % r[:3]); print(r[3][:3000])
if clean:
    print("VERDICT CLEAN"); sys.exit(0)
print("VERDICT REAL" if cat["real"] else "VERDICT ENV_ONLY")
sys.exit(1 if cat["real"] else 2)
